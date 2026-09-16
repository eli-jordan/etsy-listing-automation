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

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import ValidationError

from etsy_listings import connections
from etsy_listings.clients.etsy.tokens import EtsyAuthError
from etsy_listings.clients.etsy.transport import EtsyApiError
from etsy_listings.config.errors import ConfigLoadError
from etsy_listings.config.garment_profile import GarmentProfile
from etsy_listings.config.listing import EMPTY_DRAFT, Listing
from etsy_listings.config.listing_validation import Issue as ValidationIssue
from etsy_listings.config.listing_validation import TemplateInfo, check_listing
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.stages.etsy_target import ETSY_LISTING_ID_KEY
from etsy_listings.engine.stages.printify_product import PRODUCT_ID_KEY
from etsy_listings.engine.status import ListingStatus, edited_since_apply, listing_status
from etsy_listings.newcmd.logic import (
    build_pricing_plan_choices,
    load_candidate_pricing_plans,
    pricing_plan_ref,
    write_listing,
)
from etsy_listings.render.config import ColourMatrixTemplate, MultipleTemplate
from etsy_listings.ui.api.etsystate import live_listing_ids
from etsy_listings.ui.api.schemas import (
    CommonMediaSummary,
    CreateListingRequest,
    DraftListingRequest,
    EtsySectionSummary,
    GarmentProfileSummary,
    Issue,
    IssueCounts,
    ListingDesignSummary,
    ListingDetail,
    ListingSummary,
    PricingPlanSummary,
    RenameListingRequest,
    ResolvedPrice,
    WorkspaceSummary,
)
from etsy_listings.ui.api.thumbnails import thumbnail_response
from etsy_listings.workspace import layout
from etsy_listings.workspace.workspace import (
    InvalidNameError,
    PathEscapesWorkspaceError,
    Workspace,
)

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
    """``None`` for a profile that will not load *and* for a name that could
    never name a file at all -- ``""`` (a new listing, before the Variants
    dropdown has been touched) or anything that is not a single path segment.

    ``_segment``'s refusal is still the security boundary; all this decides is
    that an unusable value *stored in a listing* is a business issue
    (`_check_garment_profile_exists` reports it) rather than a 400 that takes
    the whole editor down with it."""
    try:
        return workspace.load_garment_profile(name)
    except (ConfigLoadError, InvalidNameError):
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


def _business_issues(workspace: Workspace, listing_dir: Path, listing: Listing) -> list[Issue]:
    """*listing_dir* rather than a listing name, because the not-yet-created
    draft the editor opens on ``/listings/new`` has no name and no directory
    -- and every ref in a listing resolves against a directory at one fixed
    depth (`listings/{name}/`), so `_any_listing_dir` answers for it exactly
    as a real one would."""
    profile = _garment_profile(workspace, listing.garment_profile)
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


def _status(workspace: Workspace, name: str, *, live: bool) -> ListingStatus:
    """This listing's place in the lifecycle
    (:mod:`etsy_listings.engine.status`).

    The two local facts are read here because they are facts about *files*:
    the lockfile records the last apply, and its own modification time is what
    a later edit to ``listing.yaml`` is compared against. The remote one --
    whether Etsy has published it -- is the caller's, since the listings table
    resolves every row's in one request.
    """
    lock = Lockfile.read(workspace.lock_file(name))
    return listing_status(
        applied=lock is not None and bool(lock.stages_completed),
        edited=edited_since_apply(workspace.listing_file(name), workspace.lock_file(name)),
        live=live,
    )


def _live(workspace: Workspace, etsy_listing_id: int | None) -> bool:
    """One listing's live-on-Etsy fact. For the single-listing endpoints; the
    table asks :func:`live_listing_ids` once for every row instead."""
    if etsy_listing_id is None:
        return False
    return etsy_listing_id in live_listing_ids(workspace.root, [etsy_listing_id])


def _pricing_summary(
    workspace: Workspace, listing_dir: Path, listing: Listing
) -> tuple[str | None, list[ResolvedPrice]]:
    """Display only (selecting a different plan from the UI is deferred): the
    resolved plan's name, and one resolved price per size -- using the
    listing's first enabled colour as representative, since the mockup's
    price table has no per-colour axis."""
    plan = None
    plan_name = None
    if listing.pricing_plan is not None:
        try:
            plan_path = workspace.resolve(listing.pricing_plan, relative_to=listing_dir)
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


def _summarize_listing(workspace: Workspace, name: str, *, live: bool) -> ListingSummary:
    listing = workspace.load_listing(name)
    etsy_listing_id, printify_product_id = _remote_ids(workspace, name)
    issues = _business_issues(workspace, workspace.listing_dir(name), listing)
    counts = IssueCounts(
        block=sum(1 for i in issues if i.severity == "block"),
        warn=sum(1 for i in issues if i.severity == "warn"),
    )
    return ListingSummary(
        name=name,
        garment_profile=listing.garment_profile,
        design=_sole_design_name(listing),
        colour_count=len(listing.colors),
        status=_status(workspace, name, live=live),
        issue_counts=counts,
        etsy_listing_id=etsy_listing_id,
        printify_product_id=printify_product_id,
    )


def _detail(
    workspace: Workspace, name: str, *, field_errors: dict[str, str] | None = None
) -> ListingDetail:
    listing = workspace.load_listing(name)
    etsy_listing_id, printify_product_id = _remote_ids(workspace, name)
    return _describe(
        workspace,
        listing,
        name=name,
        listing_dir=workspace.listing_dir(name),
        status=_status(workspace, name, live=_live(workspace, etsy_listing_id)),
        etsy_listing_id=etsy_listing_id,
        printify_product_id=printify_product_id,
        field_errors=field_errors,
    )


def _describe(
    workspace: Workspace,
    listing: Listing,
    *,
    name: str,
    listing_dir: Path,
    status: ListingStatus,
    etsy_listing_id: int | None = None,
    printify_product_id: str | None = None,
    field_errors: dict[str, str] | None = None,
) -> ListingDetail:
    """A `Listing` as the editor reads it, whether or not it is on disk.

    Split out of :func:`_detail` for the not-yet-created draft
    ``GET /api/listing-draft`` hands back: that one has no name, no lockfile
    and no directory of its own, but it must carry the same computed issues
    and the same resolved prices, or the editor would show one thing before
    the listing was named and another after.
    """
    issues = _business_issues(workspace, listing_dir, listing)
    plan_name, resolved_prices = _pricing_summary(workspace, listing_dir, listing)
    return ListingDetail.model_validate(
        {
            **listing.model_dump(mode="json"),
            "name": name,
            "status": status,
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
    """Every listing, with its status resolved in **one** Etsy round trip for
    the whole table rather than one per row -- which is why the live fact is
    gathered here and handed down rather than looked up per listing."""
    workspace = _workspace(request)
    names = workspace.listing_names()
    ids = {name: _remote_ids(workspace, name)[0] for name in names}
    live = live_listing_ids(workspace.root, [i for i in ids.values() if i is not None])
    return [
        _summarize_listing(workspace, name, live=ids[name] is not None and ids[name] in live)
        for name in names
    ]


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


def _describe_draft(
    workspace: Workspace, document: Mapping[str, Any], *, name: str = ""
) -> ListingDetail:
    """A candidate listing as the editor reads it, written nowhere.

    Two failure modes, two answers, both a 200 -- the same contract PATCH
    already has. A candidate that will not structurally validate comes back
    with ``field_errors`` over the *empty* draft, because there is no previous
    state to echo (unlike PATCH, which still has the listing on disk); one that
    will is described through :meth:`Listing.draft`, incomplete but structurally
    sound, and carries its real ``issues``.

    The client must therefore prefer its own local state to everything but
    ``field_errors`` when ``field_errors`` is set -- the issues alongside them
    describe an empty listing, not the one being edited.
    """
    currency = workspace.defaults.etsy.currency
    field_errors: dict[str, str] = {}
    try:
        listing = Listing.draft(document, currency=currency)
    except ValidationError as exc:
        listing = Listing.empty_draft(currency=currency)
        field_errors = _field_errors(exc)
    return _describe(
        workspace,
        listing,
        name=name,
        listing_dir=_any_listing_dir(workspace),
        status="draft",
        field_errors=field_errors,
    )


@router.post("", response_model=ListingDetail)
def create_listing(request: Request, body: CreateListingRequest) -> ListingDetail:
    """Naming a listing is what creates it.

    Mirrors PATCH exactly, one level up: a document that fails
    ``Listing.model_validate`` is a **200** carrying ``field_errors`` with
    nothing written, so the editor never has to branch on a status code to show
    inline validation. The two things a *name* can be wrong about keep their
    status codes instead -- not a single path segment is the 400 `_segment`
    raises through `listing_file`, and already taken is a 409.

    That 409 tests the **directory**, not ``listing.yaml``: a `listings/{name}/`
    left behind with a `state.lock.json` and no document would otherwise be
    written into, and the new listing would inherit another one's
    ``etsy_listing_id``.
    """
    workspace = _workspace(request)
    path = workspace.listing_file(body.name)
    if path.parent.exists():
        raise HTTPException(status_code=409, detail=f"a listing already exists named {body.name!r}")
    try:
        Listing.model_validate(
            body.document, context={"currency": workspace.defaults.etsy.currency}
        )
    except ValidationError:
        return _describe_draft(workspace, body.document)
    write_listing(workspace, body.name, dict(body.document))
    return _detail(workspace, body.name)


@router.post("/{name}/rename", response_model=ListingDetail)
def rename_listing(target: Existing, body: RenameListingRequest) -> ListingDetail:
    """Move a listing, whole, to a new name.

    A listing's identity is its directory name (PRD 60), so the rename is a
    directory move: ``listing.yaml``, ``state.lock.json`` and Phase 4's
    generated copy travel together, and `.cache/renders/{name}/` moves with them
    because the render cache is keyed by listing name too -- left behind it
    would orphan a tree nothing deletes and cost a full re-render.

    The lockfile's ``outputs`` keys still spell the old path afterwards, and are
    left that way deliberately: nothing reads them, they become true again at
    the next apply, and rewriting them here would breach "only the lockfile
    merges a lockfile".

    POST rather than PUT: the body is neither the listing nor its new
    representation, and a second call 404s. `POST /api/templates/{name}/kind` is
    the same shape.
    """
    workspace, old = target.workspace, target.name
    new = body.new_name
    destination = workspace.listing_dir(new)
    if new == old:
        # Blur commits an unchanged name constantly; that is not an error, and
        # it must not be the 409 below either.
        return _detail(workspace, old)
    if destination.exists():
        raise HTTPException(status_code=409, detail=f"a listing already exists named {new!r}")
    workspace.listing_dir(old).rename(destination)
    renders = workspace.renders_dir(old)
    if renders.is_dir():
        renders.rename(workspace.renders_dir(new))
    return _detail(workspace, new)


@support_router.get("/api/listing-draft", response_model=ListingDetail)
def listing_draft(request: Request) -> ListingDetail:
    """The listing `+ New listing` opens the editor on, before it has a name.

    There is no separate create *form* -- the editor itself is the form, and a
    listing is written the moment it is named and priced. What the editor needs
    first is a document to render, and inventing one in the browser would put
    the starting shape of a listing in two places, so the server hands over
    `EMPTY_DRAFT`: nothing chosen, nothing invented, and a block issue for each
    thing still to pick.

    ``name`` comes back empty, which is exactly the state the editor refuses to
    save in.
    """
    return _describe_draft(_workspace(request), EMPTY_DRAFT)


@support_router.post("/api/listing-draft", response_model=ListingDetail)
def describe_listing_draft(request: Request, body: DraftListingRequest) -> ListingDetail:
    """The same, for a candidate the editor has since edited. Writes nothing.

    The mount-time draft above answers once; this is what keeps the issues
    banner true for every edit made before the listing has a name. Without it
    the banner would still be saying "no colours enabled" about a listing whose
    colours were picked a minute ago -- and the banner is the only way an
    unsaved listing can be told what it is still missing.
    """
    return _describe_draft(_workspace(request), body.document)


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


def _any_listing_dir(workspace: Workspace) -> Path:
    """A listing directory to resolve a ref against, without naming a real
    listing. Every listing sits at the same fixed depth (`listings/{name}/`,
    the same "one fixed depth" every other bare-name ref in this module
    relies on -- `design`/`garment_profile`), so the ref this produces is the
    same regardless of which listing ultimately PATCHes it in."""
    return workspace.root / layout.LISTINGS_DIR / "_"


@support_router.get("/api/pricing-plans", response_model=list[PricingPlanSummary])
def list_pricing_plans(request: Request, garment_profile: str = "") -> list[PricingPlanSummary]:
    """Every plan, each flagged for whether it was built for this garment.

    ``garment_profile`` is optional because a listing that has not chosen one
    yet has nothing to be compatible *with*: asking with an empty name says that
    honestly, and the editor then drops the "different garment" note rather than
    labelling every plan as differing from a garment nobody picked."""
    workspace = _workspace(request)
    candidates = load_candidate_pricing_plans(workspace)
    by_path = dict(candidates)
    choices = build_pricing_plan_choices(candidates, garment_profile)
    listing_dir = _any_listing_dir(workspace)
    return [
        PricingPlanSummary(
            name=choice.value.stem,
            garment_profile=by_path[choice.value].garment_profile,
            compatible=choice.marked,
            ref=pricing_plan_ref(choice.value, listing_dir=listing_dir),
        )
        for choice in choices
    ]


@support_router.get("/api/etsy/sections", response_model=list[EtsySectionSummary])
def list_etsy_sections(request: Request) -> list[EtsySectionSummary]:
    """The live shop's sections, for the Details tab's Section dropdown.
    Empty (not a 500) for a workspace with no `shop_id` yet or no Etsy app
    key pair -- both ordinary states short of `setup`/`auth etsy`, and the
    frontend falls back to a plain text field exactly like it did before this
    endpoint existed."""
    workspace = _workspace(request)
    shop_id = workspace.defaults.etsy.shop_id
    if shop_id is None:
        return []
    client = connections.etsy_shop_client(workspace.root)
    if client is None:
        return []
    try:
        sections = client.shop_sections(shop_id)
    except (EtsyApiError, EtsyAuthError):
        return []
    return [EtsySectionSummary(id=s.shop_section_id, title=s.title) for s in sections]


@support_router.get("/api/common-media", response_model=list[CommonMediaSummary])
def list_common_media(request: Request) -> list[CommonMediaSummary]:
    """The shared assets a listing can add to `media:` as a bare path.

    Distinct from both design endpoints: ``designs/`` is the artwork that gets
    printed, ``test-designs/`` is calibration targets, and these are finished
    pictures (a sizing chart, care instructions) uploaded to Etsy as-is,
    never rendered onto a garment.
    """
    workspace = _workspace(request)
    return [
        CommonMediaSummary(
            name=path.stem,
            file=f"{layout.COMMON_MEDIA_DIR}/{path.name}",
            ref=f"../../{layout.COMMON_MEDIA_DIR}/{path.name}",
        )
        for path in workspace.common_media_files()
    ]


@support_router.get("/api/common-media/{name}/thumbnail")
def common_media_thumbnail(request: Request, name: str) -> Response:
    """An unusable *name* needs nothing here: ``InvalidNameError`` out of
    ``common_media_file`` becomes a 400 through the app-wide handler."""
    return thumbnail_response(_existing_common_media(request, name))


@support_router.get("/api/common-media/{name}/file")
def common_media_file(request: Request, name: str) -> Response:
    """The shared asset at its own size, for the editor's preview pane and its
    lightbox -- the two places a picture is *judged* rather than picked out of
    a list.

    The bytes as they sit on disk, not a re-encode: a mockup template's
    counterpart (`GET .../design-preview`) has to run the real pipeline to
    exist at all, but this file is already exactly what would be uploaded to
    Etsy, and the one thing worth seeing full-size is what Etsy will get.
    """
    path = _existing_common_media(request, name)
    return Response(
        content=path.read_bytes(),
        media_type="image/png",
        headers={"Cache-Control": "no-cache"},
    )


def _existing_common_media(request: Request, name: str) -> Path:
    path = _workspace(request).common_media_file(name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"no shared asset {name!r}")
    return path


@support_router.get("/api/workspace", response_model=WorkspaceSummary)
def get_workspace(request: Request) -> WorkspaceSummary:
    return WorkspaceSummary(shop_name=_workspace(request).defaults.etsy.shop_name)


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
