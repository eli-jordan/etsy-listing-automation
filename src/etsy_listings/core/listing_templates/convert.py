"""Save as listing template and Clone: a draft that writes nothing, then one
:func:`save`."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from etsy_listings.core.config.listing_template import ListingTemplate
from etsy_listings.core.config.listing_validation import Issue
from etsy_listings.core.errors import ConflictError, UserFacingError
from etsy_listings.core.listing_templates.check import check_listing_template_files
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.facts import WorkspaceFacts
from etsy_listings.core.workspace.trees import remove_tree
from etsy_listings.core.workspace.workspace import InvalidRefError, Workspace

_ASSETS_REF = f"./{layout.LISTING_TEMPLATE_ASSETS_DIR}/"


class UnreadableAssetError(UserFacingError, ValueError):
    def __init__(self, ref: str, detail: str) -> None:
        self.ref = ref
        super().__init__(f"{ref} cannot be copied into the listing template: {detail}")


class ListingTemplateExistsError(ConflictError, ValueError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"a listing template already exists named {name!r}")


@dataclass(frozen=True)
class AssetCopy:
    ref: str
    source: Path
    source_ref: str


@dataclass(frozen=True)
class ListingTemplateDraft:
    template: ListingTemplate
    assets: tuple[AssetCopy, ...]

    def source(self, ref: str) -> Path | None:
        return next((asset.source for asset in self.assets if asset.ref == ref), None)


def owned_refs(template: ListingTemplate) -> list[str]:
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
    def resolve(ref: str) -> Path:
        return draft.source(ref) or workspace.resolve_ref(
            ref, listing_dir=workspace.draft_listing_dir()
        )

    return check_listing_template_files(workspace, draft.template, resolve=resolve, facts=facts)


def save(
    workspace: Workspace, name: str, draft: ListingTemplateDraft, *, facts: WorkspaceFacts
) -> list[Issue]:
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
        # Last: until template.yaml lands, listing_template_names skips the directory.
        workspace.write_listing_template(name, draft.template)
    except BaseException:
        remove_tree(directory)
        raise
    return issues
