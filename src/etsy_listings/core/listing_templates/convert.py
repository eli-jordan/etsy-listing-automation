"""Save as listing template and Clone: a plan of a template, then one write
(ADR-0047, template completeness; spec *Creation and cloning*).

:func:`from_listing` and :func:`from_template` read and answer; they write
nothing. What they answer is a :class:`ListingTemplateDraft` -- the document
the template would hold and the files it would copy -- which is also exactly
what the *name it* page shows before anything exists. Only :func:`save`
touches the disk, and it refuses an incomplete draft and a name already
taken, never suffixing one: the seller chooses the name (spec, *Storage and
identity*).

A ``./`` ref is a listing's own file, and a template made from the listing
cannot point into the listing's directory -- the listing may be renamed or
deleted the next minute. So each one is planned as a copy beneath the
template's ``assets/`` and its ref rewritten to say so: ``./shots/back.png``
becomes ``./assets/shots/back.png``. The prefix rather than a flat
``assets/<file>`` keeps two refs that share a filename in different
directories apart. A bare ref is a shared workspace file and stays shared.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from etsy_listings.core.config.listing_template import ListingTemplate
from etsy_listings.core.config.listing_validation import Issue
from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.listing_templates.check import check_listing_template_files
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.facts import WorkspaceFacts
from etsy_listings.core.workspace.workspace import InvalidRefError, Workspace, remove_tree

_ASSETS_REF = f"./{layout.LISTING_TEMPLATE_ASSETS_DIR}/"


class UnreadableAssetError(UserFacingError, ValueError):
    """A ``./`` file the template would copy that cannot be read. It prevents
    the save outright (spec, *Creation and cloning*) rather than becoming a
    template with a hole in its gallery."""

    def __init__(self, ref: str, detail: str) -> None:
        self.ref = ref
        super().__init__(f"{ref} cannot be copied into the listing template: {detail}")


class ListingTemplateExistsError(UserFacingError, ValueError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"a listing template already exists named {name!r}")


@dataclass(frozen=True)
class AssetCopy:
    """One file the template will own: the ref it will name it by, the file
    on disk it is copied from, and the ref its source names that file by --
    what a picture of it has to be asked for until the copy exists."""

    ref: str
    source: Path
    source_ref: str


@dataclass(frozen=True)
class ListingTemplateDraft:
    template: ListingTemplate
    assets: tuple[AssetCopy, ...]

    def source(self, ref: str) -> Path | None:
        """Where a ref the template names lives *before* the save -- what
        the draft's checks and pictures read, since the copy does not exist
        yet."""
        return next((asset.source for asset in self.assets if asset.ref == ref), None)


def owned_refs(template: ListingTemplate) -> list[str]:
    """Every ``./`` ref a template names, once each, in order: its gallery
    files and a pricing plan kept beside the listing. The files a template
    owns -- what Save as copies in, and what staging freezes and batch
    creation copies out into each listing."""
    refs = [entry for entry in template.media if isinstance(entry, str)]
    if template.pricing_plan is not None:
        refs.append(template.pricing_plan)
    return list(dict.fromkeys(ref for ref in refs if ref.startswith("./")))


def _readable(ref: str, path: Path) -> Path:
    if not path.is_file():
        raise UnreadableAssetError(ref, "the file does not exist")
    try:
        with path.open("rb"):
            pass
    except OSError as exc:
        raise UnreadableAssetError(ref, exc.strerror or str(exc)) from exc
    return path


def from_listing(workspace: Workspace, listing: str) -> ListingTemplateDraft:
    """The spec's copy table, applied to ``listing``: garment, colours,
    pricing, gallery in order, description body (text or ref) and the four
    Etsy production settings. Design, artwork, brief, title, tags, lead and
    lifecycle are not carried, and nothing from the lockfile or any cache is
    read at all."""
    source = workspace.load_listing(listing)
    etsy = source.etsy
    template = ListingTemplate.model_validate(
        {
            "garment_profile": source.garment_profile,
            "colors": source.colors,
            "prices": source.prices,
            "pricing_plan": source.pricing_plan,
            "price_overrides": source.price_overrides,
            "media": source.media,
            "etsy": {
                # Inline text is copied deliberately: the seller chose it as
                # reusable content, and the name-it page shows it (spec).
                "description": {"text": etsy.description.text, "ref": etsy.description.ref},
                "renewal": etsy.renewal,
                "section": etsy.section,
                "shipping_profile": etsy.shipping_profile,
                "variation_images": etsy.variation_images,
            },
        },
        context={"currency": workspace.defaults.etsy.currency},
    )
    listing_dir = workspace.listing_dir(listing)
    renamed = {ref: _ASSETS_REF + ref.removeprefix("./") for ref in owned_refs(template)}
    assets = tuple(
        AssetCopy(
            ref=new,
            source=_readable(ref, _resolve_listing_ref(workspace, ref, listing_dir)),
            source_ref=ref,
        )
        for ref, new in renamed.items()
    )
    rewritten = template.model_copy(
        update={
            "media": [
                renamed.get(entry, entry) if isinstance(entry, str) else entry
                for entry in template.media
            ],
            "pricing_plan": renamed.get(template.pricing_plan, template.pricing_plan)
            if template.pricing_plan is not None
            else None,
        }
    )
    return ListingTemplateDraft(template=rewritten, assets=assets)


def _resolve_listing_ref(workspace: Workspace, ref: str, listing_dir: Path) -> Path:
    try:
        return workspace.resolve_ref(ref, listing_dir=listing_dir)
    except InvalidRefError as exc:
        raise UnreadableAssetError(ref, exc.detail) from exc


def from_template(workspace: Workspace, template: str) -> ListingTemplateDraft:
    """Clone: the same document, with every template-owned file planned as a
    copy into the clone's own directory, so the two share nothing and either
    can be deleted (spec, *Creation and cloning*). The refs need no rewrite --
    they already name the template's own directory."""
    document = workspace.load_listing_template(template)
    assets: list[AssetCopy] = []
    for ref in owned_refs(document):
        try:
            path = workspace.resolve_template_ref(ref, template=template)
        except InvalidRefError as exc:
            raise UnreadableAssetError(ref, exc.detail) from exc
        assets.append(AssetCopy(ref=ref, source=_readable(ref, path), source_ref=ref))
    return ListingTemplateDraft(template=document, assets=tuple(assets))


def draft_issues(
    workspace: Workspace, draft: ListingTemplateDraft, *, facts: WorkspaceFacts
) -> list[Issue]:
    """The draft's completeness, judged against the files it will copy
    -- they are the same bytes the saved template will hold."""

    def resolve(ref: str) -> Path:
        return draft.source(ref) or workspace.resolve_ref(
            ref, listing_dir=workspace.draft_listing_dir()
        )

    return check_listing_template_files(workspace, draft.template, resolve=resolve, facts=facts)


def save(
    workspace: Workspace, name: str, draft: ListingTemplateDraft, *, facts: WorkspaceFacts
) -> list[Issue]:
    """Write ``draft`` as listing template ``name``, or refuse and write
    nothing.

    A taken name raises :class:`ListingTemplateExistsError` -- the
    *directory* is what is tested, so a half-written one left by a crash is
    taken too, and never written into. An incomplete draft answers its
    issues, with a ``block`` among them, and writes nothing; otherwise
    the answer is the draft's remaining warnings and the template exists.

    The directory is made first, the assets copied into it, and
    ``template.yaml`` written last and atomically: until that file lands,
    `Workspace.listing_template_names` does not count the directory, and a
    failure part-way removes it.
    """
    directory = workspace.listing_template_dir(name)
    if directory.exists():
        raise ListingTemplateExistsError(name)
    issues = draft_issues(workspace, draft, facts=facts)
    if any(issue.severity == "block" for issue in issues):
        return issues
    try:
        directory.mkdir(parents=True)
    except FileExistsError as exc:
        raise ListingTemplateExistsError(name) from exc
    try:
        for asset in draft.assets:
            target = workspace.resolve_template_ref(asset.ref, template=name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(asset.source, target)
        workspace.write_listing_template(name, draft.template)
    except BaseException:
        remove_tree(directory)
        raise
    return issues
