"""Listings UI endpoints (phase-5-listings-ui.md): the dashboard/editor's
``/api/listings*`` surface, plus the read-only endpoints the editor's pickers
need (garment profiles, pricing plans, designs).

Follows ``templates.py``'s conventions exactly: a ``target()`` dependency for
existence-checking, ``Listing`` reused directly for the read/write body (the
wire shape *is* ``listing.yaml``), new API-only schemas only where the shape
genuinely differs, expected domain errors caught locally and raised as
``HTTPException`` rather than relying on a shared handler.

Validation is two-tier, and only the first tier lives here as a direct call --
the second is a whole module (``config/listing_validation.py``):

* **Structural** -- does the candidate even parse as a ``Listing``? A
  ``Listing.model_validate`` failure blocks the write and comes back as
  ``field_errors`` on the (unchanged) ``ListingDetail``.
* **Business** -- pydantic-valid but incomplete (empty media, a `<generate>`
  title, a colour-swatch template missing a colour). Reused via
  ``check_listing``, surfaced as the ``issues`` list. This layer's only job is
  assembling that function's inputs from the workspace: which garment profile
  resolved (or didn't), which design paths resolved, and what every
  referenced template's real kind and colours are.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import ValidationError

from etsy_listings.config.errors import ConfigLoadError
from etsy_listings.config.garment_profile import GarmentProfile
from etsy_listings.config.listing import Listing
from etsy_listings.config.listing_validation import Issue as ValidationIssue
from etsy_listings.config.listing_validation import TemplateInfo, check_listing
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.stages.etsy_target import ETSY_LISTING_ID_KEY
from etsy_listings.engine.stages.printify_product import PRODUCT_ID_KEY
from etsy_listings.newcmd.logic import (
    build_listing_stub,
    build_pricing_plan_choices,
    load_candidate_pricing_plans,
    pricing_plan_ref,
    validate_listing_stub,
    write_listing,
)
from etsy_listings.render.config import ColourMatrixTemplate, MultipleTemplate
from etsy_listings.ui.api.schemas import (
    CreateListingRequest,
    GarmentProfileSummary,
    Issue,
    IssueCounts,
    ListingDesignSummary,
    ListingDetail,
    ListingStatus,
    ListingSummary,
    PricingPlanSummary,
    ResolvedPrice,
)
from etsy_listings.ui.api.thumbnails import thumbnail_response
from etsy_listings.workspace.workspace import PathEscapesWorkspaceError, Workspace

router = APIRouter(prefix="/api/listings", tags=["listings"])

# Distinct prefixes from `router` above (garment profiles/pricing plans/
# designs are not listings), so they get their own router rather than being
# force-fit under "/api/listings".
support_router = APIRouter(tags=["listings-support"])


def _workspace(request: Request) -> Workspace:
    workspace: Workspace = request.app.state.workspace
    return workspace


@dataclass(frozen=True)
class Target:
    workspace: Workspace
    name: str


def target(request: Request, name: str) -> Target:
    workspace = _workspace(request)
    if not workspace.listing_file(name).is_file():
        raise HTTPException(status_code=404, detail=f"no listing {name!r}")
    return Target(workspace=workspace, name=name)


Existing = Annotated[Target, Depends(target)]


def _garment_profile(workspace: Workspace, name: str) -> GarmentProfile | None:
    try:
        return workspace.load_garment_profile(name)
    except ConfigLoadError:
        return None


def _resolve_design_paths(
    workspace: Workspace, listing: Listing, listing_dir: Path
) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for key, ref in listing.design.items():
        try:
            paths[key] = workspace.resolve(ref, relative_to=listing_dir)
        except PathEscapesWorkspaceError:
            continue
    return paths


def _template_info_map(workspace: Workspace) -> dict[str, TemplateInfo]:
    """Every *calibrated* template's real kind and colours, the way
    ``check_listing`` needs them -- an uncalibrated one has no kind to compare
    against and is silently skipped, the same as a template name that has
    since been renamed or deleted from under a listing."""
    result: dict[str, TemplateInfo] = {}
    for name in workspace.template_names():
        try:
            config = workspace.load_template_config(name)
        except ConfigLoadError:
            continue
        if isinstance(config, ColourMatrixTemplate):
            colours = frozenset(workspace.template_colours(name))
        elif isinstance(config, MultipleTemplate):
            colours = frozenset(p.colour for p in config.placements if p.colour)
        else:
            colours = frozenset({config.colour}) if config.colour else frozenset()
        result[name] = TemplateInfo(kind=config.kind, colours=colours)
    return result


def _business_issues(workspace: Workspace, name: str, listing: Listing) -> list[Issue]:
    profile = _garment_profile(workspace, listing.garment_profile)
    listing_dir = workspace.listing_dir(name)
    raw_issues: list[ValidationIssue] = check_listing(
        listing,
        garment_profile=profile,
        garment_profile_names=workspace.garment_profile_names(),
        design_paths=_resolve_design_paths(workspace, listing, listing_dir),
        templates=_template_info_map(workspace),
    )
    return [
        Issue(severity=i.severity, tab=i.tab, where=i.where, message=i.message) for i in raw_issues
    ]


def _remote_ids(workspace: Workspace, name: str) -> tuple[int | None, str | None]:
    lock = Lockfile.read(workspace.lock_file(name))
    if lock is None:
        return None, None
    raw_etsy = lock.remote.get(ETSY_LISTING_ID_KEY)
    raw_product = lock.remote.get(PRODUCT_ID_KEY)
    return (int(raw_etsy) if raw_etsy else None), (str(raw_product) if raw_product else None)


def _status(etsy_listing_id: int | None) -> ListingStatus:
    return "published" if etsy_listing_id is not None else "draft"


def _pricing_summary(
    workspace: Workspace, name: str, listing: Listing
) -> tuple[str | None, list[ResolvedPrice]]:
    """Display only (selecting a different plan from the UI is deferred): the
    resolved plan's name, and one resolved price per size -- using the
    listing's first enabled colour as representative, since the mockup's
    price table has no per-colour axis."""
    plan = None
    plan_name = None
    if listing.pricing_plan is not None:
        try:
            plan_path = workspace.resolve(
                listing.pricing_plan, relative_to=workspace.listing_dir(name)
            )
            plan = workspace.load_pricing_plan(plan_path)
            plan_name = plan_path.stem
        except (PathEscapesWorkspaceError, ConfigLoadError):
            plan = None
            plan_name = None

    profile = _garment_profile(workspace, listing.garment_profile)
    sizes = profile.sizes if profile is not None else sorted(listing.prices)
    colour = listing.colors[0] if listing.colors else ""
    prices: list[ResolvedPrice] = []
    for size in sizes:
        try:
            money = listing.resolved_price(colour, size, pricing_plan=plan)
        except KeyError:
            continue
        prices.append(ResolvedPrice(size=size, amount=str(money)))
    return plan_name, prices


def _sole_design_name(listing: Listing) -> str | None:
    """The one design's name, or ``None`` when there isn't one.

    ``Listing.design`` is artwork-key -> path, and a bare string normalises to
    a single ``default`` entry -- the common case, and the only one with a
    picture that stands for the whole listing. The stem is what
    ``GET /api/listing-designs/{name}/thumbnail`` takes, since
    ``workspace.design_file`` derives one fixed path per name.
    """
    if len(listing.design) != 1:
        return None
    return Path(next(iter(listing.design.values()))).stem


def _summarize_listing(workspace: Workspace, name: str) -> ListingSummary:
    listing = workspace.load_listing(name)
    etsy_listing_id, _ = _remote_ids(workspace, name)
    issues = _business_issues(workspace, name, listing)
    counts = IssueCounts(
        block=sum(1 for i in issues if i.severity == "block"),
        warn=sum(1 for i in issues if i.severity == "warn"),
    )
    return ListingSummary(
        name=name,
        garment_profile=listing.garment_profile,
        design=_sole_design_name(listing),
        colour_count=len(listing.colors),
        status=_status(etsy_listing_id),
        issue_counts=counts,
    )


def _detail(
    workspace: Workspace, name: str, *, field_errors: dict[str, str] | None = None
) -> ListingDetail:
    listing = workspace.load_listing(name)
    issues = _business_issues(workspace, name, listing)
    etsy_listing_id, printify_product_id = _remote_ids(workspace, name)
    plan_name, resolved_prices = _pricing_summary(workspace, name, listing)
    return ListingDetail.model_validate(
        {
            **listing.model_dump(mode="json"),
            "name": name,
            "status": _status(etsy_listing_id),
            "issues": [i.model_dump() for i in issues],
            "field_errors": field_errors or {},
            "etsy_listing_id": etsy_listing_id,
            "printify_product_id": printify_product_id,
            "pricing_plan_name": plan_name,
            "resolved_prices": [p.model_dump() for p in resolved_prices],
        },
        context={"currency": workspace.defaults.etsy.currency},
    )


def _field_errors(exc: ValidationError) -> dict[str, str]:
    result: dict[str, str] = {}
    for error in exc.errors():
        loc = ".".join(str(part) for part in error["loc"]) or "__root__"
        result[loc] = error["msg"]
    return result


def _merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """A shallow merge, except ``etsy:``, which merges one level deep -- the
    editor's tabs each own a slice of it (title, tags, section, ...) and a
    shallow overwrite there would let a Details-tab autosave silently erase
    whatever the last PATCH wrote to a sibling field."""
    merged = dict(base)
    for key, value in patch.items():
        if key == "etsy" and isinstance(value, dict) and isinstance(merged.get("etsy"), dict):
            merged["etsy"] = {**merged["etsy"], **value}
        else:
            merged[key] = value
    return merged


@router.get("", response_model=list[ListingSummary])
def list_listings(request: Request) -> list[ListingSummary]:
    workspace = _workspace(request)
    return [_summarize_listing(workspace, name) for name in workspace.listing_names()]


@router.get("/{name}", response_model=ListingDetail)
def get_listing(target: Existing) -> ListingDetail:
    return _detail(target.workspace, target.name)


@router.patch("/{name}", response_model=ListingDetail)
def patch_listing(target: Existing, body: dict[str, Any]) -> ListingDetail:
    workspace, name = target.workspace, target.name
    path = workspace.listing_file(name)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    merged = _merge(raw, body)
    try:
        Listing.model_validate(merged, context={"currency": workspace.defaults.etsy.currency})
    except ValidationError as exc:
        return _detail(workspace, name, field_errors=_field_errors(exc))
    path.write_text(yaml.safe_dump(merged, sort_keys=False), encoding="utf-8")
    return _detail(workspace, name)


@router.post("", response_model=ListingDetail)
def create_listing(request: Request, body: CreateListingRequest) -> ListingDetail:
    workspace = _workspace(request)
    if workspace.listing_file(body.name).is_file():
        raise HTTPException(status_code=409, detail=f"a listing already exists named {body.name!r}")

    design_path = workspace.design_file(body.design)
    if not design_path.is_file():
        raise HTTPException(status_code=400, detail=f"no such design {body.design!r}")

    if body.garment_profile not in workspace.garment_profile_names():
        raise HTTPException(
            status_code=400, detail=f"no such garment profile {body.garment_profile!r}"
        )

    candidates = load_candidate_pricing_plans(workspace)
    choices = build_pricing_plan_choices(candidates, body.garment_profile)
    compatible = [c for c in choices if c.marked]
    if not compatible:
        raise HTTPException(
            status_code=400,
            detail=(
                "no pricing plan exists for this garment profile -- create one with "
                "`etsy-listings new` or by hand"
            ),
        )
    plan_ref = pricing_plan_ref(compatible[0].value, listing_dir=workspace.listing_dir(body.name))

    listing_data = build_listing_stub(
        garment_profile_slug=body.garment_profile,
        design_ref=f"../../designs/{body.design}.png",
        colours=body.colors,
        pricing_plan_ref=plan_ref,
        brief="",
        media=[],
    )
    validate_listing_stub(listing_data, currency=workspace.defaults.etsy.currency)
    write_listing(workspace, body.name, listing_data)
    return _detail(workspace, body.name)


@support_router.get("/api/garment-profiles", response_model=list[GarmentProfileSummary])
def list_garment_profiles(request: Request) -> list[GarmentProfileSummary]:
    workspace = _workspace(request)
    result = []
    for name in workspace.garment_profile_names():
        profile = _garment_profile(workspace, name)
        if profile is None:
            continue
        result.append(GarmentProfileSummary(name=name, sizes=profile.sizes, colors=profile.colors))
    return result


@support_router.get("/api/pricing-plans", response_model=list[PricingPlanSummary])
def list_pricing_plans(request: Request, garment_profile: str) -> list[PricingPlanSummary]:
    workspace = _workspace(request)
    candidates = load_candidate_pricing_plans(workspace)
    by_path = dict(candidates)
    choices = build_pricing_plan_choices(candidates, garment_profile)
    return [
        PricingPlanSummary(
            name=choice.value.stem,
            garment_profile=by_path[choice.value].garment_profile,
            compatible=choice.marked,
        )
        for choice in choices
    ]


@support_router.get("/api/listing-designs", response_model=list[ListingDesignSummary])
def list_listing_designs(request: Request) -> list[ListingDesignSummary]:
    workspace = _workspace(request)
    return [
        ListingDesignSummary(name=path.stem, file=f"designs/{path.name}")
        for path in workspace.design_files()
    ]


@support_router.get("/api/listing-designs/{name}/thumbnail")
def listing_design_thumbnail(request: Request, name: str) -> Response:
    """The artwork itself, downscaled -- what the listings table, its hover
    card and the editor's design strip all show.

    Distinct from ``designs.py``'s calibrator library for the same reason
    ``GET /api/listing-designs`` is: ``designs/`` holds artwork that ships,
    ``test-designs/`` holds calibration targets, and a listing's design is
    never one of the latter.

    An unusable *name* needs nothing here: ``InvalidNameError`` out of
    ``design_file`` becomes a 400 through the app-wide handler in ``app.py``.
    """
    workspace = _workspace(request)
    path = workspace.design_file(name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"no design {name!r}")
    return thumbnail_response(path)
