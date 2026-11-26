"""Listing template operations: list, read, draft, create, edit, rename and
delete.

Every write takes the template's write lock and re-checks the template under it,
so a create and a rename to one name cannot both win."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import ValidationError

from etsy_listings.core import listing_templates as conversion
from etsy_listings.core.application.listing_reads import PricedSize, pricing_summary
from etsy_listings.core.application.refusals import (
    ListingMissingError,
    ListingTemplateMissingError,
    ListingTemplateSourceRefusedError,
    ReservedListingTemplateNameError,
    field_errors_of,
)
from etsy_listings.core.batches import BatchRecords, BatchStore
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
from etsy_listings.core.workspace import locks
from etsy_listings.core.workspace.facts import WorkspaceFacts
from etsy_listings.core.workspace.listing_documents import ListingDocuments
from etsy_listings.core.workspace.workspace import Workspace

RESERVED_NAME = "draft"
"""The *name it* page's route, ``GET /api/listing-templates/draft``."""


@dataclass(frozen=True)
class TemplateSource:
    kind: Literal["listing", "listing-template"]
    name: str


@dataclass(frozen=True)
class ListingTemplateView:
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
    height)``."""


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
    _require(workspace, name)
    return _saved_view(workspace, WorkspaceFacts.gather(workspace), name)


@dataclass(frozen=True)
class DraftOrigin:
    """Where a new listing template is drafted from: exactly one of a listing
    (Save as listing template) or another template (Clone)."""

    listing: str | None = None
    template: str | None = None


def draft_listing_template(workspace: Workspace, origin: DraftOrigin) -> ListingTemplateView:
    source, draft = _draft(workspace, origin)
    facts = WorkspaceFacts.gather(workspace)
    return _view(
        workspace,
        facts,
        draft.template,
        draft_issues(workspace, draft, facts=facts),
        _TemplateContext(
            name="",
            resolve=lambda ref: (
                draft.source(ref)
                or workspace.resolve_ref(ref, listing_dir=workspace.draft_listing_dir())
            ),
            source=source,
            assets=draft.assets,
        ),
    )


def create_listing_template(
    workspace: Workspace,
    name: str,
    origin: DraftOrigin,
    *,
    document: Mapping[str, Any] | None = None,
) -> TemplateSave:
    _check_name(workspace, name)
    _, draft = _draft(workspace, origin)
    if document is not None:
        try:
            draft = _edited(draft, document, currency=workspace.defaults.etsy.currency)
        except ValidationError as exc:
            return TemplateSave(saved=False, issues=[], field_errors=field_errors_of(exc))
    facts = WorkspaceFacts.gather(workspace)
    with locks.hold(workspace, "listing-template", name):
        issues = conversion.save(workspace, name, draft, facts=facts)
    if _blocked(issues):
        return TemplateSave(saved=False, issues=issues)
    return TemplateSave(saved=True, issues=issues, template=_saved_view(workspace, facts, name))


def edit_listing_template(
    workspace: Workspace, name: str, document: Mapping[str, Any]
) -> TemplateSave:
    facts = WorkspaceFacts.gather(workspace)
    with locks.hold(workspace, "listing-template", name):
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
    records: BatchRecords,
) -> None:
    destination = workspace.listing_template_dir(new)
    if new == RESERVED_NAME:
        raise ReservedListingTemplateNameError(new)
    with locks.hold(workspace, "listing-template", old, new):
        _require(workspace, old)
        if new == old:
            return
        if destination.exists():
            raise ListingTemplateExistsError(new)
        workspace.listing_template_dir(old).rename(destination)
        # Not atomic with the move: a crash between leaves records naming a gone template.
        records.rename_listing_template(old, new)


def delete_listing_template(workspace: Workspace, name: str) -> None:
    with locks.hold(workspace, "listing-template", name):
        _require(workspace, name)
        workspace.remove_listing_template(name)


def _require(workspace: Workspace, name: str) -> Path:
    path = workspace.listing_template_file(name)
    if not path.is_file():
        raise ListingTemplateMissingError(name)
    return path


def _check_name(workspace: Workspace, name: str) -> None:
    workspace.listing_template_dir(name)  # InvalidNameError for a non-segment
    if name == RESERVED_NAME:
        raise ReservedListingTemplateNameError(name)


def _blocked(issues: list[Issue]) -> bool:
    return any(issue.severity == "block" for issue in issues)


def _garment(profile: GarmentProfile | None) -> str | None:
    if profile is None:
        return None
    return f"{profile.blueprint.brand} {profile.blueprint.model}"


def _plan_name(template: ListingTemplate) -> str | None:
    return PurePosixPath(template.pricing_plan).stem if template.pricing_plan else None


def _draft(
    workspace: Workspace, origin: DraftOrigin
) -> tuple[TemplateSource, ListingTemplateDraft]:
    listing, template = origin.listing, origin.template
    if (listing is None) == (template is None):
        raise ListingTemplateSourceRefusedError("give exactly one of from_listing, from_template")
    try:
        if listing is not None:
            if not ListingDocuments(workspace).exists(listing):
                raise ListingMissingError(listing)
            return TemplateSource("listing", listing), conversion.from_listing(workspace, listing)
        assert template is not None  # exactly one, checked above
        _require(workspace, template)
        return TemplateSource("listing-template", template), conversion.from_template(
            workspace, template
        )
    except (UnreadableAssetError, ConfigLoadError) as exc:
        raise ListingTemplateSourceRefusedError(str(exc)) from exc


def _edited(
    draft: ListingTemplateDraft, document: Mapping[str, Any], *, currency: str
) -> ListingTemplateDraft:
    template = ListingTemplate.model_validate(dict(document), context={"currency": currency})
    planned = {asset.ref for asset in draft.assets}
    unplanned = [ref for ref in conversion.owned_refs(template) if ref not in planned]
    if unplanned:
        raise ListingTemplateSourceRefusedError(
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
        _TemplateContext(
            name=name,
            resolve=lambda ref: workspace.resolve_template_ref(ref, template=name),
            modified_at=datetime.fromtimestamp(modified, tz=UTC),
        ),
    )


@dataclass(frozen=True)
class _TemplateContext:
    name: str
    resolve: Callable[[str], Path]
    modified_at: datetime | None = None
    source: TemplateSource | None = None
    assets: tuple[AssetCopy, ...] = ()


def _view(
    workspace: Workspace,
    facts: WorkspaceFacts,
    template: ListingTemplate,
    issues: list[Issue],
    context: _TemplateContext,
) -> ListingTemplateView:
    _, resolved_prices = pricing_summary(workspace, facts, template, resolve=context.resolve)
    body = template.etsy.description
    described = workspace.resolve_description(DescriptionConfig(text=body.text, ref=body.ref))
    return ListingTemplateView(
        name=context.name,
        template=template,
        issues=issues,
        garment_profile=facts.garment_profile(template.garment_profile),
        resolved_prices=resolved_prices,
        description_composed=described.composed,
        modified_at=context.modified_at,
        source=context.source,
        assets=context.assets,
    )
