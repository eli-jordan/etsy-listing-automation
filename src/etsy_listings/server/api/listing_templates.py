"""Listing-template endpoints (ADR-0047, template completeness; batch plan PR 1): the Listing
templates page's index, the *name it* page's draft, create (Save as listing
template and Clone), read, valid-only ``PUT``, rename and delete.

The operations are
:mod:`etsy_listings.core.application.listing_template_library`'s
(module-structure plan, PR 7); this module only projects their answers
onto the wire, in the listings endpoints' idiom. Their refusals pass through to
the app's one refusal table (``app.py``'s ``REFUSAL_STATUS``):

* A **name** the server will not take is a status code -- ``400`` for one
  that is not a single path segment or is ``draft``, ``409`` for one already
  taken, which is never suffixed.
* A **document** it will not write is a ``200`` with ``saved: false`` and the
  issues or field errors, and nothing on disk changes. That is what lets
  the editor keep the seller's values and say why.
* A **source** that cannot become a template -- no such listing, a ``./``
  file that cannot be read -- is ``404`` or ``422`` with the sentence.

``GET /draft`` is declared before ``GET /{name}``, so ``draft`` is refused as
a name: a template called that could be created and never opened.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response

from etsy_listings.core.application import listing_template_library as library
from etsy_listings.core.application.listing_template_library import (
    ListingTemplateView,
    TemplateSave,
)
from etsy_listings.core.batches import BatchRecords
from etsy_listings.core.config.listing_validation import Issue as ValidationIssue
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api import app_state
from etsy_listings.server.api.editor_projections import garment_fields, wire_prices
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

router = APIRouter(prefix="/api/listing-templates", tags=["listing-templates"])


def _wire(issues: list[ValidationIssue]) -> list[Issue]:
    return [Issue(severity=i.severity, tab=i.tab, where=i.where, message=i.message) for i in issues]


def _detail(workspace: Workspace, view: ListingTemplateView) -> ListingTemplateDetail:
    profile = view.garment_profile
    return ListingTemplateDetail.model_validate(
        {
            **view.template.model_dump(mode="json"),
            "issues": [i.model_dump() for i in _wire(view.issues)],
            "garment": view.garment,
            "pricing_plan_name": view.pricing_plan_name,
            "resolved_prices": [p.model_dump() for p in wire_prices(view.resolved_prices)],
            **garment_fields(profile),
            "description_composed": view.description_composed,
            "name": view.name,
            "modified_at": view.modified_at,
            **(
                {
                    "source": ListingTemplateSource(
                        kind=view.source.kind, name=view.source.name
                    ).model_dump(),
                    "assets": [
                        ListingTemplateAsset(ref=a.ref, source_ref=a.source_ref).model_dump()
                        for a in view.assets
                    ],
                }
                if view.source is not None
                else {}
            ),
        },
        context={"currency": workspace.defaults.etsy.currency},
    )


def _save_result(workspace: Workspace, outcome: TemplateSave) -> ListingTemplateSaveResult:
    return ListingTemplateSaveResult(
        saved=outcome.saved,
        issues=_wire(outcome.issues),
        field_errors=outcome.field_errors,
        template=_detail(workspace, outcome.template) if outcome.template is not None else None,
    )


@router.get("", response_model=list[ListingTemplateSummary])
def list_listing_templates(request: Request) -> list[ListingTemplateSummary]:
    """Every listing template, as its card on the Listing templates page shows
    it (UI doc §2)."""
    return [
        ListingTemplateSummary(
            name=card.name,
            garment=card.garment,
            colour_count=len(card.template.colors),
            pricing_plan_name=card.pricing_plan_name,
            media=card.template.media,
            batch_count=card.batch_count,
            design_minimum=(
                PixelSize(width=card.design_minimum[0], height=card.design_minimum[1])
                if card.design_minimum is not None
                else None
            ),
        )
        for card in library.list_listing_templates(
            app_state.workspace(request), batches=app_state.batch_store(request)
        )
    ]


@router.get("/draft", response_model=ListingTemplateDetail)
def listing_template_draft(
    request: Request, from_listing: str | None = None, from_template: str | None = None
) -> ListingTemplateDetail:
    """The template Save as listing template or Clone would write, written
    nowhere: what the *name it* page shows before the seller commits a name
    (UI doc §1)."""
    workspace = app_state.workspace(request)
    view = library.draft_listing_template(
        workspace, library.DraftOrigin(listing=from_listing, template=from_template)
    )
    return _detail(workspace, view)


@router.post("", response_model=ListingTemplateSaveResult)
def create_listing_template(
    request: Request, body: CreateListingTemplateRequest
) -> ListingTemplateSaveResult:
    """Naming the draft is what writes it (UI doc §1). The name is checked
    first, so a bad one is a 400 before any source is read."""
    workspace = app_state.workspace(request)
    outcome = library.create_listing_template(
        workspace,
        body.name,
        library.DraftOrigin(listing=body.from_listing, template=body.from_template),
        document=body.document,
    )
    return _save_result(workspace, outcome)


@router.get("/{name}", response_model=ListingTemplateDetail)
def get_listing_template(request: Request, name: str) -> ListingTemplateDetail:
    workspace = app_state.workspace(request)
    view = library.read_listing_template(workspace, name)
    return _detail(workspace, view)


@router.put("/{name}", response_model=ListingTemplateSaveResult)
def put_listing_template(
    request: Request, name: str, body: dict[str, Any]
) -> ListingTemplateSaveResult:
    """template completeness: write the whole document only if it is complete. A malformed or
    incomplete one leaves ``template.yaml`` byte-for-byte as it was, so the
    server always holds the last complete version; the listing-template editor
    keeps the unsaved values on its side."""
    workspace = app_state.workspace(request)
    outcome = library.edit_listing_template(workspace, name, body)
    return _save_result(workspace, outcome)


@router.post("/{name}/rename", response_model=ListingTemplateDetail)
def rename_listing_template(
    request: Request, name: str, body: RenameListingRequest
) -> ListingTemplateDetail:
    """Move a listing template, whole, to a new name -- double-click the
    name, exactly as a listing (UI doc §3). A taken name is a 409 and never
    suffixed (spec, *Storage and identity*); the staging sessions and
    batches made from it follow it by name
    (:func:`~etsy_listings.core.application.listing_template_library.rename_listing_template`)."""
    workspace = app_state.workspace(request)
    library.rename_listing_template(
        workspace,
        name,
        body.new_name,
        records=BatchRecords(app_state.staging_store(request), app_state.batch_store(request)),
    )
    view = library.read_listing_template(workspace, body.new_name)
    return _detail(workspace, view)


@router.delete("/{name}", status_code=204)
def delete_listing_template(request: Request, name: str) -> Response:
    """Allowed whatever was made from it: batches keep their own frozen copy,
    and a listing never had a link to it (spec, *Completeness and editing*)."""
    library.delete_listing_template(app_state.workspace(request), name)
    return Response(status_code=204)
