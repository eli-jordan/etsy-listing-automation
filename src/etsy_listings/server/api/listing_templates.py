"""Listing-template endpoints (ADR-0047, template completeness; batch plan PR 1): the Listing
templates page's index, the *name it* page's draft, create (Save as listing
template and Clone), read, valid-only ``PUT`` and delete.

The rules are `listing_templates`'; this module decides only what each
answer is on the wire, in the listings endpoints' idiom:

* A **name** the server will not take is a status code -- ``400`` for one
  that is not a single path segment (the app-wide ``InvalidNameError``
  handler), ``409`` for one already taken, which is never suffixed.
* A **document** it will not write is a ``200`` with ``saved: false`` and the
  issues or field errors, and nothing on disk changes. That is what lets
  the editor keep the seller's values and say why.
* A **source** that cannot become a template -- no such listing, a ``./``
  file that cannot be read -- is ``404`` or ``422`` with the sentence.

``GET /draft`` is declared before ``GET /{name}``, so ``draft`` is refused as
a name: a template called that could be created and never opened.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import ValidationError

# By module: the draft endpoint's query parameters are called ``from_listing``
# and ``from_template`` (the plan's route), which would shadow the functions.
from etsy_listings.core import listing_templates as conversion
from etsy_listings.core.batches import BatchStore, StagingStore
from etsy_listings.core.config.description import DescriptionConfig
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.config.listing_template import ListingTemplate
from etsy_listings.core.config.listing_validation import Issue as ValidationIssue
from etsy_listings.core.config.listing_validation import required_design_pixels
from etsy_listings.core.listing_templates import (
    ListingTemplateDraft,
    ListingTemplateExistsError,
    UnreadableAssetError,
    draft_issues,
    save,
    template_issues,
)
from etsy_listings.core.workspace.facts import WorkspaceFacts
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.listings import field_errors_of, pricing_summary
from etsy_listings.server.api.schemas import (
    CreateListingTemplateRequest,
    Issue,
    ListingTemplateAsset,
    ListingTemplateDetail,
    ListingTemplateSaveResult,
    ListingTemplateSource,
    ListingTemplateSummary,
    PixelSize,
    RenameListingRequest,
)
from etsy_listings.server.workspace_locks import WorkspaceLocks

router = APIRouter(prefix="/api/listing-templates", tags=["listing-templates"])


def _workspace(request: Request) -> Workspace:
    workspace: Workspace = request.app.state.workspace
    return workspace


def _locks(request: Request) -> WorkspaceLocks:
    locks: WorkspaceLocks = request.app.state.workspace_locks
    return locks


def _batch_store(request: Request) -> BatchStore:
    store: BatchStore = request.app.state.batch_store
    return store


def _require(workspace: Workspace, name: str) -> Path:
    path = workspace.listing_template_file(name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"no listing template {name!r}")
    return path


def _wire(issues: list[ValidationIssue]) -> list[Issue]:
    return [Issue(severity=i.severity, tab=i.tab, where=i.where, message=i.message) for i in issues]


def _blocked(issues: list[ValidationIssue]) -> bool:
    return any(issue.severity == "block" for issue in issues)


def _garment(facts: WorkspaceFacts, template: ListingTemplate) -> str | None:
    profile = facts.garment_profile(template.garment_profile)
    if profile is None:
        return None
    return f"{profile.blueprint.brand} {profile.blueprint.model}"


def _design_minimum(facts: WorkspaceFacts, template: ListingTemplate) -> PixelSize | None:
    profile = facts.garment_profile(template.garment_profile)
    if profile is None:
        return None
    width, height = required_design_pixels(profile)
    return PixelSize(width=width, height=height)


def _plan_name(template: ListingTemplate) -> str | None:
    """The plan ref's stem, read off the ref rather than the file: a name to
    show, which needs no plan to load."""
    return PurePosixPath(template.pricing_plan).stem if template.pricing_plan else None


def _view(
    workspace: Workspace,
    facts: WorkspaceFacts,
    template: ListingTemplate,
    issues: list[ValidationIssue],
    *,
    resolve: Callable[[str], Path],
) -> dict[str, Any]:
    """The document, its issues, and what the listing editor's tabs compute
    for a listing -- prices, materials, the composed description -- by the
    listing's own rules (UI doc §3: the tabs are mounted unchanged).
    ``resolve`` finds a ``./`` ref wherever the template's files are: its
    own directory once saved, the files it will copy while a draft."""
    profile = facts.garment_profile(template.garment_profile)
    _, resolved_prices = pricing_summary(workspace, facts, template, resolve=resolve)
    body = template.etsy.description
    described = workspace.resolve_description(DescriptionConfig(text=body.text, ref=body.ref))
    return {
        **template.model_dump(mode="json"),
        "issues": [i.model_dump() for i in _wire(issues)],
        "garment": _garment(facts, template),
        "pricing_plan_name": _plan_name(template),
        "resolved_prices": [p.model_dump() for p in resolved_prices],
        "garment_materials": profile.materials if profile is not None else [],
        "garment_product_type": profile.blueprint.display_title if profile is not None else None,
        "garment_brand": profile.blueprint.brand if profile is not None else None,
        "garment_model": profile.blueprint.model if profile is not None else None,
        "description_composed": described.composed,
    }


def _detail(workspace: Workspace, facts: WorkspaceFacts, name: str) -> ListingTemplateDetail:
    template = workspace.load_listing_template(name)
    issues = template_issues(workspace, name, template, facts=facts)
    modified = workspace.listing_template_file(name).stat().st_mtime
    return ListingTemplateDetail.model_validate(
        {
            **_view(
                workspace,
                facts,
                template,
                issues,
                resolve=lambda ref: workspace.resolve_template_ref(ref, template=name),
            ),
            "name": name,
            "modified_at": datetime.fromtimestamp(modified, tz=UTC),
        },
        context={"currency": workspace.defaults.etsy.currency},
    )


def _draft(
    workspace: Workspace, *, listing: str | None, template: str | None
) -> tuple[ListingTemplateSource, ListingTemplateDraft]:
    """The draft a create or the draft endpoint starts from. Exactly one of
    the two sources; a missing one is a 404, and one that cannot become a
    template -- a ``./`` file gone, a ``listing.yaml`` that will not load --
    a 422 saying why."""
    if (listing is None) == (template is None):
        raise HTTPException(
            status_code=422, detail="give exactly one of from_listing, from_template"
        )
    try:
        if listing is not None:
            if not workspace.listing_file(listing).is_file():
                raise HTTPException(status_code=404, detail=f"no listing {listing!r}")
            return ListingTemplateSource(kind="listing", name=listing), conversion.from_listing(
                workspace, listing
            )
        assert template is not None  # noqa: S101 - exactly one, checked above
        _require(workspace, template)
        return ListingTemplateSource(
            kind="listing-template", name=template
        ), conversion.from_template(workspace, template)
    except (UnreadableAssetError, ConfigLoadError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _edited(
    draft: ListingTemplateDraft, document: dict[str, Any], *, currency: str
) -> ListingTemplateDraft:
    """``draft`` with the seller's edited document in place of the source's.
    It copies only the files the edit still names, and a ``./`` ref it does
    not plan to copy is refused: the draft has no directory yet, so such a
    ref could only name a file that will never be there."""
    template = ListingTemplate.model_validate(document, context={"currency": currency})
    planned = {asset.ref for asset in draft.assets}
    unplanned = [ref for ref in conversion.owned_refs(template) if ref not in planned]
    if unplanned:
        raise HTTPException(
            status_code=422,
            detail=f"{unplanned[0]} is not one of the files this listing template copies",
        )
    kept = set(conversion.owned_refs(template))
    return ListingTemplateDraft(
        template=template, assets=tuple(a for a in draft.assets if a.ref in kept)
    )


@router.get("", response_model=list[ListingTemplateSummary])
def list_listing_templates(request: Request) -> list[ListingTemplateSummary]:
    """Every listing template, as its card on the Listing templates page shows
    it (UI doc §2). A template whose file will not load is left out rather
    than failing the page; it can only get that way by a hand edit."""
    workspace = _workspace(request)
    facts = WorkspaceFacts.gather(workspace)
    used = Counter(batch.listing_template for batch in _batch_store(request).all())
    cards: list[ListingTemplateSummary] = []
    for name in workspace.listing_template_names():
        try:
            template = workspace.load_listing_template(name)
        except ConfigLoadError:
            continue
        cards.append(
            ListingTemplateSummary(
                name=name,
                garment=_garment(facts, template) or template.garment_profile,
                colour_count=len(template.colors),
                pricing_plan_name=_plan_name(template),
                media=template.media,
                batch_count=used[name],
                design_minimum=_design_minimum(facts, template),
            )
        )
    return cards


@router.get("/draft", response_model=ListingTemplateDetail)
def listing_template_draft(
    request: Request, from_listing: str | None = None, from_template: str | None = None
) -> ListingTemplateDetail:
    """The template Save as listing template or Clone would write, written
    nowhere: what the *name it* page shows before the seller commits a name
    (UI doc §1)."""
    workspace = _workspace(request)
    source, draft = _draft(workspace, listing=from_listing, template=from_template)
    facts = WorkspaceFacts.gather(workspace)
    return ListingTemplateDetail.model_validate(
        {
            **_view(
                workspace,
                facts,
                draft.template,
                draft_issues(workspace, draft, facts=facts),
                resolve=lambda ref: (
                    draft.source(ref)
                    or workspace.resolve_ref(ref, listing_dir=workspace.draft_listing_dir())
                ),
            ),
            "name": "",
            "modified_at": None,
            "source": source.model_dump(),
            "assets": [
                ListingTemplateAsset(ref=a.ref, source_ref=a.source_ref).model_dump()
                for a in draft.assets
            ],
        },
        context={"currency": workspace.defaults.etsy.currency},
    )


@router.post("", response_model=ListingTemplateSaveResult)
def create_listing_template(
    request: Request, body: CreateListingTemplateRequest
) -> ListingTemplateSaveResult:
    """Naming the draft is what writes it (UI doc §1). The name is checked
    first, so a bad one is a 400 before any source is read."""
    workspace = _workspace(request)
    workspace.listing_template_dir(body.name)
    if body.name == "draft":
        raise HTTPException(status_code=400, detail="'draft' is reserved; pick another name")
    _, draft = _draft(workspace, listing=body.from_listing, template=body.from_template)
    if body.document is not None:
        try:
            draft = _edited(draft, body.document, currency=workspace.defaults.etsy.currency)
        except ValidationError as exc:
            return ListingTemplateSaveResult(
                saved=False, issues=[], field_errors=field_errors_of(exc)
            )
    facts = WorkspaceFacts.gather(workspace)
    with _locks(request).listing_template(body.name):
        try:
            issues = save(workspace, body.name, draft, facts=facts)
        except ListingTemplateExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    if _blocked(issues):
        return ListingTemplateSaveResult(saved=False, issues=_wire(issues))
    return ListingTemplateSaveResult(
        saved=True, issues=_wire(issues), template=_detail(workspace, facts, body.name)
    )


@router.get("/{name}", response_model=ListingTemplateDetail)
def get_listing_template(request: Request, name: str) -> ListingTemplateDetail:
    workspace = _workspace(request)
    _require(workspace, name)
    return _detail(workspace, WorkspaceFacts.gather(workspace), name)


@router.put("/{name}", response_model=ListingTemplateSaveResult)
def put_listing_template(
    request: Request, name: str, body: dict[str, Any]
) -> ListingTemplateSaveResult:
    """template completeness: write the whole document only if it is complete. A malformed or
    incomplete one leaves ``template.yaml`` byte-for-byte as it was, so the
    server always holds the last complete version; the listing-template editor
    (PR 6) keeps the unsaved values on its side."""
    workspace = _workspace(request)
    facts = WorkspaceFacts.gather(workspace)
    with _locks(request).listing_template(name):
        _require(workspace, name)
        try:
            template = ListingTemplate.model_validate(
                body, context={"currency": workspace.defaults.etsy.currency}
            )
        except ValidationError as exc:
            return ListingTemplateSaveResult(
                saved=False, issues=[], field_errors=field_errors_of(exc)
            )
        issues = template_issues(workspace, name, template, facts=facts)
        if _blocked(issues):
            return ListingTemplateSaveResult(saved=False, issues=_wire(issues))
        workspace.write_listing_template(name, template)
    return ListingTemplateSaveResult(
        saved=True, issues=_wire(issues), template=_detail(workspace, facts, name)
    )


@router.post("/{name}/rename", response_model=ListingTemplateDetail)
def rename_listing_template(
    request: Request, name: str, body: RenameListingRequest
) -> ListingTemplateDetail:
    """Move a listing template, whole, to a new name -- double-click the
    name, exactly as a listing (UI doc §3). Its name is its directory,
    so the rename is a directory move and its ``./`` refs, which name that
    directory, need no rewrite. A taken name is a 409 and never suffixed
    (spec, *Storage and identity*).

    Staging sessions and batch records made from it follow it by name --
    the name, not the frozen copy they each keep, which is untouched.
    That name is the card's *Used by N batches* and the staging page's
    *Using X*, the seller's link between a template and its batches. It
    is rewritten after the move, under each record's lock; a crash between
    the two leaves records naming a template that is gone, which is what a
    delete leaves too, and harms nothing a batch needs."""
    workspace = _workspace(request)
    new = body.new_name
    destination = workspace.listing_template_dir(new)
    if new == "draft":
        raise HTTPException(status_code=400, detail="'draft' is reserved; pick another name")
    with _locks(request).listing_template(name, new):
        _require(workspace, name)
        if new != name:
            if destination.exists():
                raise HTTPException(
                    status_code=409, detail=f"a listing template already exists named {new!r}"
                )
            workspace.listing_template_dir(name).rename(destination)
            staging_store: StagingStore = request.app.state.staging_store
            staging_store.rename_listing_template(name, new)
            _batch_store(request).rename_listing_template(name, new)
    return _detail(workspace, WorkspaceFacts.gather(workspace), new)


@router.delete("/{name}", status_code=204)
def delete_listing_template(request: Request, name: str) -> Response:
    """Allowed whatever was made from it: batches keep their own frozen copy,
    and a listing never had a link to it (spec, *Completeness and editing*)."""
    workspace = _workspace(request)
    with _locks(request).listing_template(name):
        _require(workspace, name)
        workspace.remove_listing_template(name)
    return Response(status_code=204)
