"""The Listing templates page and editor: the index, the *name it* draft,
create (Save as listing template, Clone), read, the valid-only edit, rename
and delete (ADR-0047, template completeness; spec *Listing templates*;
module-structure plan, PR 7).

The conversion and completeness rules are ``listing_templates``'
(``from_listing``, ``from_template``, ``save``, ``template_issues``); this
module coordinates them with the template's write lock and with the records
that name a template. Every write takes ``ListingTemplateLocks`` and
re-checks the template once it holds it, so a create and a rename to one
name cannot both win, and an edit waiting behind a rename finds the template
gone rather than recreating it under the old name.

Two kinds of "no", as for a listing (``refusals``): a *name* or a *source*
the operation cannot take is raised, with nothing written; a *document* it
will not write -- malformed, or complete but for a blocking issue -- is
answered as a :class:`TemplateSave` with ``saved`` false, leaving
``template.yaml`` byte-for-byte as it was so the server always holds the
last complete version.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import ValidationError

from etsy_listings.core import listing_templates as conversion
from etsy_listings.core.application.dependencies import ListingTemplateLocks
from etsy_listings.core.application.listing_reads import PricedSize, pricing_summary
from etsy_listings.core.application.refusals import (
    ListingMissing,
    ListingTemplateMissing,
    ListingTemplateSourceRefused,
    ReservedListingTemplateName,
    field_errors_of,
)
from etsy_listings.core.batches import BatchStore, StagingStore
from etsy_listings.core.config.description import DescriptionConfig
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.config.garment_profile import GarmentProfile
from etsy_listings.core.config.listing_template import ListingTemplate
from etsy_listings.core.config.listing_validation import Issue, required_design_pixels
from etsy_listings.core.listing_templates import (
    AssetCopy,
    ListingTemplateDraft,
    ListingTemplateExistsError,
    UnreadableAssetError,
    draft_issues,
    template_issues,
)
from etsy_listings.core.workspace.facts import WorkspaceFacts
from etsy_listings.core.workspace.workspace import Workspace

RESERVED_NAME = "draft"
"""The *name it* page's route, ``GET /api/listing-templates/draft``."""


@dataclass(frozen=True)
class TemplateSource:
    """What a draft is made from: Save as listing template, or Clone."""

    kind: Literal["listing", "listing-template"]
    name: str


@dataclass(frozen=True)
class ListingTemplateView:
    """A listing template as its pages read it, saved or not -- the document,
    its issues, and what the listing editor's tabs compute for a listing by
    the listing's own rules, since the template editor mounts those tabs
    unchanged (UI doc §3).

    A draft has ``name`` ``""``, no ``modified_at``, and says where it came
    from in ``source`` and the files it will copy in ``assets``."""

    name: str
    template: ListingTemplate
    issues: list[Issue]
    garment_profile: GarmentProfile | None
    resolved_prices: list[PricedSize]
    description_composed: str
    """The body alone: a template has no lead."""
    modified_at: datetime | None = None
    source: TemplateSource | None = None
    assets: tuple[AssetCopy, ...] = ()

    @property
    def garment(self) -> str | None:
        return _garment(self.garment_profile)

    @property
    def pricing_plan_name(self) -> str | None:
        return _plan_name(self.template)


@dataclass(frozen=True)
class ListingTemplateCard:
    """One card on the Listing templates page (UI doc §2)."""

    name: str
    template: ListingTemplate
    garment: str
    """The blueprint as a seller names it, or the profile's own name when it
    will not load."""
    pricing_plan_name: str | None
    batch_count: int
    """Batches made from it, while their records last."""
    design_minimum: tuple[int, int] | None
    """The smallest design the garment's print area takes, ``(width,
    height)`` -- New batch's size hint (UI doc §4)."""


@dataclass(frozen=True)
class TemplateSave:
    """What a create or an edit did. ``saved`` false: nothing was written,
    and ``issues`` (a ``block`` among them) or ``field_errors`` say why.
    Saved: ``issues`` are the warnings left, and ``template`` the template
    as it now reads."""

    saved: bool
    issues: list[Issue]
    field_errors: dict[str, str] = field(default_factory=dict)
    template: ListingTemplateView | None = None


# -------------------------------------------------------------------- reads


def list_listing_templates(
    workspace: Workspace, *, batches: BatchStore
) -> list[ListingTemplateCard]:
    """Every listing template's card. One whose file will not load is left
    out rather than failing the page -- only a hand edit makes one."""
    facts = WorkspaceFacts.gather(workspace)
    used = Counter(batch.listing_template for batch in batches.all())
    cards: list[ListingTemplateCard] = []
    for name in workspace.listing_template_names():
        try:
            template = workspace.load_listing_template(name)
        except ConfigLoadError:
            continue
        profile = facts.garment_profile(template.garment_profile)
        cards.append(
            ListingTemplateCard(
                name=name,
                template=template,
                garment=_garment(profile) or template.garment_profile,
                pricing_plan_name=_plan_name(template),
                batch_count=used[name],
                design_minimum=required_design_pixels(profile) if profile is not None else None,
            )
        )
    return cards


def read_listing_template(workspace: Workspace, name: str) -> ListingTemplateView:
    """Listing template ``name``, with the issues it has now -- its shared
    refs can have changed under it since it was saved complete."""
    _require(workspace, name)
    return _saved_view(workspace, WorkspaceFacts.gather(workspace), name)


def draft_listing_template(
    workspace: Workspace, *, from_listing: str | None, from_template: str | None
) -> ListingTemplateView:
    """The template Save as listing template or Clone would write, written
    nowhere -- what the *name it* page shows before a name is committed."""
    source, draft = _draft(workspace, listing=from_listing, template=from_template)
    facts = WorkspaceFacts.gather(workspace)
    return _view(
        workspace,
        facts,
        draft.template,
        draft_issues(workspace, draft, facts=facts),
        resolve=lambda ref: (
            draft.source(ref)
            or workspace.resolve_ref(ref, listing_dir=workspace.draft_listing_dir())
        ),
        name="",
        source=source,
        assets=draft.assets,
    )


# ------------------------------------------------------------------- writes


def create_listing_template(
    workspace: Workspace,
    name: str,
    *,
    from_listing: str | None,
    from_template: str | None,
    document: Mapping[str, Any] | None = None,
    locks: ListingTemplateLocks,
) -> TemplateSave:
    """Naming the draft is what writes it (UI doc §1).

    The name is checked first, so an unusable one (``InvalidNameError``) or
    ``draft`` (:class:`ReservedListingTemplateName`) is refused before any
    source is read. Then the source: exactly one, existing
    (:class:`ListingMissing`, :class:`ListingTemplateMissing`), and able to
    become a template (:class:`ListingTemplateSourceRefused`). ``document``
    is the seller's edit made before naming: it replaces the source's, and
    only the files it still names are copied. Under the name's write lock, a
    name already taken -- the *directory*, even half-written -- raises
    ``ListingTemplateExistsError`` and is never suffixed.
    """
    _check_name(workspace, name)
    _, draft = _draft(workspace, listing=from_listing, template=from_template)
    if document is not None:
        try:
            draft = _edited(draft, document, currency=workspace.defaults.etsy.currency)
        except ValidationError as exc:
            return TemplateSave(saved=False, issues=[], field_errors=field_errors_of(exc))
    facts = WorkspaceFacts.gather(workspace)
    with locks.listing_template(name):
        issues = conversion.save(workspace, name, draft, facts=facts)
    if _blocked(issues):
        return TemplateSave(saved=False, issues=issues)
    return TemplateSave(saved=True, issues=issues, template=_saved_view(workspace, facts, name))


def edit_listing_template(
    workspace: Workspace, name: str, document: Mapping[str, Any], *, locks: ListingTemplateLocks
) -> TemplateSave:
    """Write the whole ``document`` as listing template ``name``, only if it
    is complete (template completeness). :class:`ListingTemplateMissing`
    when there is none, before or after waiting for its lock."""
    facts = WorkspaceFacts.gather(workspace)
    with locks.listing_template(name):
        _require(workspace, name)
        try:
            template = ListingTemplate.model_validate(
                dict(document), context={"currency": workspace.defaults.etsy.currency}
            )
        except ValidationError as exc:
            return TemplateSave(saved=False, issues=[], field_errors=field_errors_of(exc))
        issues = template_issues(workspace, name, template, facts=facts)
        if _blocked(issues):
            return TemplateSave(saved=False, issues=issues)
        workspace.write_listing_template(name, template)
    return TemplateSave(saved=True, issues=issues, template=_saved_view(workspace, facts, name))


def rename_listing_template(
    workspace: Workspace,
    old: str,
    new: str,
    *,
    locks: ListingTemplateLocks,
    staging: StagingStore,
    batches: BatchStore,
) -> None:
    """Move a listing template, whole, to ``new``. Its name is its
    directory, so its ``./`` refs need no rewrite.

    Staging sessions and batch records made from it follow it by *name* --
    the card's *Used by N batches*, the staging page's *Using X* -- while the
    frozen copy each keeps is untouched. They are rewritten after the move,
    each under its own lock; a crash between leaves records naming a
    template that is gone, which is what a delete leaves too. Renaming to
    the same name changes nothing. Refusals: ``InvalidNameError``,
    :class:`ReservedListingTemplateName`, :class:`ListingTemplateMissing`,
    ``ListingTemplateExistsError``.
    """
    destination = workspace.listing_template_dir(new)
    if new == RESERVED_NAME:
        raise ReservedListingTemplateName(new)
    with locks.listing_template(old, new):
        _require(workspace, old)
        if new == old:
            return
        if destination.exists():
            raise ListingTemplateExistsError(new)
        workspace.listing_template_dir(old).rename(destination)
        staging.rename_listing_template(old, new)
        batches.rename_listing_template(old, new)


def delete_listing_template(
    workspace: Workspace, name: str, *, locks: ListingTemplateLocks
) -> None:
    """Allowed whatever was made from it: batches keep their own frozen
    copy, and a listing never had a link to it (spec, *Completeness and
    editing*)."""
    with locks.listing_template(name):
        _require(workspace, name)
        workspace.remove_listing_template(name)


# ------------------------------------------------------------------ helpers


def _require(workspace: Workspace, name: str) -> Path:
    path = workspace.listing_template_file(name)
    if not path.is_file():
        raise ListingTemplateMissing(name)
    return path


def _check_name(workspace: Workspace, name: str) -> None:
    workspace.listing_template_dir(name)  # InvalidNameError for a non-segment
    if name == RESERVED_NAME:
        raise ReservedListingTemplateName(name)


def _blocked(issues: list[Issue]) -> bool:
    return any(issue.severity == "block" for issue in issues)


def _garment(profile: GarmentProfile | None) -> str | None:
    if profile is None:
        return None
    return f"{profile.blueprint.brand} {profile.blueprint.model}"


def _plan_name(template: ListingTemplate) -> str | None:
    """The plan ref's stem, read off the ref: a name to show, which needs no
    plan to load."""
    return PurePosixPath(template.pricing_plan).stem if template.pricing_plan else None


def _draft(
    workspace: Workspace, *, listing: str | None, template: str | None
) -> tuple[TemplateSource, ListingTemplateDraft]:
    if (listing is None) == (template is None):
        raise ListingTemplateSourceRefused("give exactly one of from_listing, from_template")
    try:
        if listing is not None:
            if not workspace.listing_file(listing).is_file():
                raise ListingMissing(listing)
            return TemplateSource("listing", listing), conversion.from_listing(workspace, listing)
        assert template is not None  # noqa: S101 - exactly one, checked above
        _require(workspace, template)
        return TemplateSource("listing-template", template), conversion.from_template(
            workspace, template
        )
    except (UnreadableAssetError, ConfigLoadError) as exc:
        raise ListingTemplateSourceRefused(str(exc)) from exc


def _edited(
    draft: ListingTemplateDraft, document: Mapping[str, Any], *, currency: str
) -> ListingTemplateDraft:
    """``draft`` with the seller's edited document in place of the source's.
    Only the files the edit still names are copied, and a ``./`` ref it does
    not plan to copy is refused: the draft has no directory yet, so such a
    ref could only name a file that will never be there."""
    template = ListingTemplate.model_validate(dict(document), context={"currency": currency})
    planned = {asset.ref for asset in draft.assets}
    unplanned = [ref for ref in conversion.owned_refs(template) if ref not in planned]
    if unplanned:
        raise ListingTemplateSourceRefused(
            f"{unplanned[0]} is not one of the files this listing template copies"
        )
    kept = set(conversion.owned_refs(template))
    return ListingTemplateDraft(
        template=template, assets=tuple(a for a in draft.assets if a.ref in kept)
    )


def _saved_view(workspace: Workspace, facts: WorkspaceFacts, name: str) -> ListingTemplateView:
    template = workspace.load_listing_template(name)
    modified = workspace.listing_template_file(name).stat().st_mtime
    return _view(
        workspace,
        facts,
        template,
        template_issues(workspace, name, template, facts=facts),
        resolve=lambda ref: workspace.resolve_template_ref(ref, template=name),
        name=name,
        modified_at=datetime.fromtimestamp(modified, tz=UTC),
    )


def _view(
    workspace: Workspace,
    facts: WorkspaceFacts,
    template: ListingTemplate,
    issues: list[Issue],
    *,
    resolve: Callable[[str], Path],
    name: str,
    modified_at: datetime | None = None,
    source: TemplateSource | None = None,
    assets: tuple[AssetCopy, ...] = (),
) -> ListingTemplateView:
    """``resolve`` finds a ``./`` ref wherever the template's files are: its
    own directory once saved, the files it will copy while a draft."""
    _, resolved_prices = pricing_summary(workspace, facts, template, resolve=resolve)
    body = template.etsy.description
    described = workspace.resolve_description(DescriptionConfig(text=body.text, ref=body.ref))
    return ListingTemplateView(
        name=name,
        template=template,
        issues=issues,
        garment_profile=facts.garment_profile(template.garment_profile),
        resolved_prices=resolved_prices,
        description_composed=described.composed,
        modified_at=modified_at,
        source=source,
        assets=assets,
    )
