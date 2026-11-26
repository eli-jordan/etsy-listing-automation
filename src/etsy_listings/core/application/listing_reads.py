from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from etsy_listings.core.application.dependencies import EtsyStates
from etsy_listings.core.application.refusals import ListingMissingError, field_errors_of
from etsy_listings.core.config.artwork import Resolved, resolve
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.config.garment_profile import GarmentProfile
from etsy_listings.core.config.listing import Listing
from etsy_listings.core.config.listing_validation import (
    CheckInputs,
    Issue,
    check_listing,
    check_listing_yaml_present,
)
from etsy_listings.core.config.money import Money
from etsy_listings.core.config.pricing_plan import PricingPlan
from etsy_listings.core.config.settings import SettingsProblem
from etsy_listings.core.config.template_positions import TemplatePositions, layer_boxes
from etsy_listings.core.engine.status import (
    ListingGesture,
    ListingStatus,
    is_live_etsy_state,
    listing_gestures,
    remote_ids,
    workspace_listing_status,
)
from etsy_listings.core.render.config import LayerBoxes
from etsy_listings.core.workspace.facts import WorkspaceFacts
from etsy_listings.core.workspace.listing_documents import ListingDocuments
from etsy_listings.core.workspace.workspace import DescriptionResolution, InvalidRefError, Workspace


@dataclass(frozen=True)
class PricedSize:
    size: str
    amount: Money


class Priced(Protocol):
    garment_profile: str
    colors: list[str]
    pricing_plan: str | None

    @property
    def prices(self) -> Mapping[str, Money]: ...

    def resolved_price(
        self, color: str, size: str, *, pricing_plan: PricingPlan | None = None
    ) -> Money: ...


@dataclass(frozen=True)
class ListingView:
    name: str
    listing: Listing
    status: ListingStatus
    issues: list[Issue]
    gestures: tuple[ListingGesture, ...]
    description_composed: str
    design_content_hash: str | None
    pricing_plan_name: str | None
    resolved_prices: list[PricedSize]
    garment_profile: GarmentProfile | None
    modified_at: datetime | None = None
    etsy_listing_id: int | None = None
    printify_product_id: str | None = None
    field_errors: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ListingRow:
    name: str
    listing: Listing | None
    status: ListingStatus
    issues: list[Issue]
    gestures: tuple[ListingGesture, ...]
    etsy_listing_id: int | None
    printify_product_id: str | None


def read_listing(workspace: Workspace, name: str, *, etsy_states: EtsyStates) -> ListingView:
    if not ListingDocuments(workspace).exists(name):
        raise ListingMissingError(name)
    listing = workspace.load_listing(name)
    etsy_listing_id, printify_product_id = remote_ids(workspace, name)
    etsy_state = _etsy_state(etsy_states, etsy_listing_id)
    published = is_live_etsy_state(etsy_state)
    return _describe(
        workspace,
        WorkspaceFacts.gather(workspace),
        listing,
        _ListingContext(
            name=name,
            listing_dir=workspace.listing_dir(name),
            published=published,
            status=workspace_listing_status(
                workspace, name, live=published, lifecycle=listing.lifecycle, etsy_state=etsy_state
            ),
            gestures=listing_gestures(
                lifecycle=listing.lifecycle, etsy_state=etsy_state, published=published
            ),
            modified_at=datetime.fromtimestamp(
                workspace.listing_file(name).stat().st_mtime, tz=UTC
            ),
            etsy_listing_id=etsy_listing_id,
            printify_product_id=printify_product_id,
        ),
    )


@dataclass(frozen=True)
class ListingScenes:
    artwork: Callable[[str | None], Path | None]
    """:func:`scene_artwork`'s answer."""
    positions: TemplatePositions | None

    def boxes(self, template: str) -> LayerBoxes:
        return layer_boxes(self.positions, template)


def listing_scenes(workspace: Workspace, name: str) -> ListingScenes:
    if not ListingDocuments(workspace).exists(name):
        raise ListingMissingError(name)
    listing = workspace.load_listing(name)
    return ListingScenes(
        artwork=_artwork(workspace, name, listing), positions=listing.template_positions
    )


def scene_artwork(workspace: Workspace, name: str) -> Callable[[str | None], Path | None]:
    return listing_scenes(workspace, name).artwork


def _artwork(
    workspace: Workspace, name: str, listing: Listing
) -> Callable[[str | None], Path | None]:
    profile = WorkspaceFacts.for_files(workspace).garment_profile(listing.garment_profile)
    tones = profile.colors if profile is not None else {}
    listing_dir = workspace.listing_dir(name)

    def artwork(colour: str | None) -> Path | None:
        resolution = resolve(listing.design, colour, tones)
        if not isinstance(resolution, Resolved):
            return None
        try:
            path = workspace.resolve_ref(resolution.ref, listing_dir=listing_dir)
        except InvalidRefError:
            return None
        return path if path.is_file() else None

    return artwork


def describe_draft(workspace: Workspace, document: Mapping[str, Any]) -> ListingView:
    currency = workspace.defaults.etsy.currency
    field_errors: dict[str, str] = {}
    try:
        listing = Listing.model_validate(dict(document), context={"currency": currency})
    except ValidationError as exc:
        listing = Listing.empty_draft(currency=currency)
        field_errors = field_errors_of(exc)
    return _describe(
        workspace,
        WorkspaceFacts.gather(workspace),
        listing,
        _ListingContext(
            name="",
            listing_dir=workspace.draft_listing_dir(),
            published=False,
            status="draft",
            gestures=(),
            field_errors=field_errors,
        ),
    )


class PhaseTimer:
    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self._clock = clock
        self.seconds: dict[str, float] = {}

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        start = self._clock()
        try:
            yield
        finally:
            self.seconds[name] = self.seconds.get(name, 0.0) + self._clock() - start


def list_listings(
    workspace: Workspace, *, etsy_states: EtsyStates, timer: PhaseTimer | None = None
) -> list[ListingRow]:
    timer = timer if timer is not None else PhaseTimer()
    with timer.phase("catalogue"):
        facts = WorkspaceFacts.gather(workspace)
    with timer.phase("ids"):
        names = workspace.listing_names()
        ids = {name: remote_ids(workspace, name)[0] for name in names}
    with timer.phase("etsy"):
        states = etsy_states([i for i in ids.values() if i is not None])
    return [
        listing_row(
            workspace,
            name,
            etsy_state=states.get(listing_id) if (listing_id := ids[name]) is not None else None,
            facts=facts,
            timer=timer,
        )
        for name in names
    ]


def listing_row(
    workspace: Workspace,
    name: str,
    *,
    etsy_state: str | None,
    facts: WorkspaceFacts | None = None,
    timer: PhaseTimer | None = None,
) -> ListingRow:
    facts = facts if facts is not None else WorkspaceFacts.gather(workspace)
    timer = timer if timer is not None else PhaseTimer()
    etsy_listing_id, printify_product_id = remote_ids(workspace, name)
    published = is_live_etsy_state(etsy_state)
    if not ListingDocuments(workspace).exists(name):
        return ListingRow(
            name=name,
            listing=None,
            status=workspace_listing_status(workspace, name, live=published, etsy_state=etsy_state),
            issues=check_listing_yaml_present(present=False),
            gestures=(),
            etsy_listing_id=etsy_listing_id,
            printify_product_id=printify_product_id,
        )
    with timer.phase("load"):
        listing = workspace.load_listing(name)
        description = workspace.resolve_description(listing.etsy.description)
    published = published if etsy_listing_id is not None else False
    listing_dir = workspace.listing_dir(name)
    with timer.phase("status"):
        status = workspace_listing_status(
            workspace, name, live=published, lifecycle=listing.lifecycle, etsy_state=etsy_state
        )
    with timer.phase("inputs"):
        inputs = _check_inputs(facts, listing, listing_dir, description, name=name)
    with timer.phase("checks"):
        issues = _business_issues(workspace, listing_dir, listing, inputs, published=published)
    return ListingRow(
        name=name,
        listing=listing,
        status=status,
        issues=issues,
        gestures=listing_gestures(
            lifecycle=listing.lifecycle, etsy_state=etsy_state, published=published
        ),
        etsy_listing_id=etsy_listing_id,
        printify_product_id=printify_product_id,
    )


def pricing_summary(
    workspace: Workspace,
    facts: WorkspaceFacts,
    priced: Priced,
    *,
    resolve: Callable[[str], Path],
) -> tuple[str | None, list[PricedSize]]:
    plan = None
    plan_name = None
    if priced.pricing_plan is not None:
        try:
            plan_path = resolve(priced.pricing_plan)
            plan = workspace.load_pricing_plan(plan_path)
            plan_name = plan_path.stem
        except ConfigLoadError:
            plan = None
            plan_name = None

    profile = facts.garment_profile(priced.garment_profile)
    sizes = profile.sizes if profile is not None else sorted(priced.prices)
    representative_colour = priced.colors[0] if priced.colors else ""
    prices: list[PricedSize] = []
    for size in sizes:
        try:
            money = priced.resolved_price(representative_colour, size, pricing_plan=plan)
        except KeyError:
            continue
        prices.append(PricedSize(size=size, amount=money))
    return plan_name, prices


def _etsy_state(etsy_states: EtsyStates, etsy_listing_id: int | None) -> str | None:
    if etsy_listing_id is None:
        return None
    return etsy_states([etsy_listing_id]).get(etsy_listing_id)


@dataclass(frozen=True)
class _ListingContext:
    name: str
    listing_dir: Path
    published: bool
    status: ListingStatus
    gestures: Sequence[ListingGesture]
    modified_at: datetime | None = None
    etsy_listing_id: int | None = None
    printify_product_id: str | None = None
    field_errors: dict[str, str] | None = None


def _describe(
    workspace: Workspace, facts: WorkspaceFacts, listing: Listing, context: _ListingContext
) -> ListingView:
    listing_dir = context.listing_dir
    description = workspace.resolve_description(listing.etsy.description)
    issues = _business_issues(
        workspace,
        listing_dir,
        listing,
        _check_inputs(facts, listing, listing_dir, description, name=context.name),
        published=context.published,
    )
    plan_name, resolved_prices = pricing_summary(
        workspace,
        facts,
        listing,
        resolve=lambda ref: workspace.resolve_ref(ref, listing_dir=listing_dir),
    )
    return ListingView(
        name=context.name,
        listing=listing,
        status=context.status,
        issues=issues,
        gestures=tuple(context.gestures),
        description_composed=description.composed,
        design_content_hash=workspace.design_content_hash(listing.design, listing_dir=listing_dir),
        pricing_plan_name=plan_name,
        resolved_prices=resolved_prices,
        garment_profile=facts.garment_profile(listing.garment_profile),
        modified_at=context.modified_at,
        etsy_listing_id=context.etsy_listing_id,
        printify_product_id=context.printify_product_id,
        field_errors=context.field_errors or {},
    )


def _check_inputs(
    facts: WorkspaceFacts,
    listing: Listing,
    listing_dir: Path,
    description: DescriptionResolution,
    *,
    name: str,
) -> CheckInputs:
    inputs = CheckInputs(
        garment_profile=facts.garment_profile(listing.garment_profile),
        garment_profile_names=facts.garment_profile_names,
        templates=facts.templates,
        description_ref_error=str(description.error) if description.error is not None else None,
        videos=facts.videos(listing, listing_dir),
        listing_name=name,
    )
    if not listing.template_positions:
        return inputs
    settings = facts.settings()
    if isinstance(settings, SettingsProblem):
        return replace(inputs, template_position_limits_error=settings.message)
    return replace(inputs, template_position_limits=settings.template_positions)


def _business_issues(
    workspace: Workspace,
    listing_dir: Path,
    listing: Listing,
    inputs: CheckInputs,
    *,
    published: bool,
) -> list[Issue]:
    """*listing_dir* rather than a listing name, because the unnamed draft
    has no directory. A workspace-rooted ref resolves the same against any
    listing directory, so `Workspace.draft_listing_dir` answers for it
    exactly as a real one would."""
    return check_listing(
        listing,
        inputs,
        design_paths=_resolve_design_paths(workspace, listing, listing_dir),
        published=published,
    )


def _resolve_design_paths(
    workspace: Workspace, listing: Listing, listing_dir: Path
) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for key, ref in listing.design.items():
        if ref is None:
            continue
        try:
            paths[key] = workspace.resolve_ref(ref, listing_dir=listing_dir)
        except InvalidRefError:
            continue
    return paths
