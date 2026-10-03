"""A listing as the editor and the listings table read it.

Two-tier validation, and only the first tier is decided here:

* **Structural** -- does a candidate even parse as a ``Listing``? A draft that
  does not is described as the empty draft beside its ``field_errors``.
* **Business** -- valid but incomplete (empty media, a blank title, a
  colour-swatch template missing a colour). That is
  ``config/listing_validation.py``'s ``check_listing``, applied here, never
  restated; its issues ride along unchanged.

Status and gestures are ``engine/status.py``'s, from the same facts for the
table's row and the editor's detail, so the two cannot disagree. The one fact
the workspace cannot answer -- Etsy's state for a listing -- arrives through
:data:`~etsy_listings.core.application.dependencies.EtsyStates`, asked once
per read. Assembling ``check_listing``'s inputs is ``WorkspaceFacts``' job: a
read gathers it once however many listings it describes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from etsy_listings.core.application.dependencies import EtsyStates
from etsy_listings.core.application.refusals import ListingMissing, field_errors_of
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.config.garment_profile import GarmentProfile
from etsy_listings.core.config.listing import Listing
from etsy_listings.core.config.listing_validation import (
    Issue,
    check_listing,
    check_listing_yaml_present,
)
from etsy_listings.core.config.money import Money
from etsy_listings.core.config.pricing_plan import PricingPlan
from etsy_listings.core.engine.status import (
    ListingGesture,
    ListingStatus,
    is_live_etsy_state,
    listing_gestures,
    remote_ids,
    workspace_listing_status,
)
from etsy_listings.core.workspace.facts import WorkspaceFacts
from etsy_listings.core.workspace.listing_documents import ListingDocuments
from etsy_listings.core.workspace.workspace import InvalidRefError, Workspace


@dataclass(frozen=True)
class PricedSize:
    """One size's resolved price."""

    size: str
    amount: Money


class Priced(Protocol):
    """What a price summary reads: a listing, or a listing template, which
    carries the same price fields and the same resolution."""

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
    """Everything the editor shows about one listing, saved or not.

    ``field_errors`` is set only when a candidate failed structural
    validation; the rest then describes what is on disk (an edit) or the
    empty draft (an unsaved candidate), never the rejected document.
    """

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
    """One row of the listings table. ``listing`` is ``None`` for a
    directory left with a lockfile and no ``listing.yaml``, whose one issue
    says so."""

    name: str
    listing: Listing | None
    status: ListingStatus
    issues: list[Issue]
    gestures: tuple[ListingGesture, ...]
    etsy_listing_id: int | None
    printify_product_id: str | None


def read_listing(workspace: Workspace, name: str, *, etsy_states: EtsyStates) -> ListingView:
    """Listing ``name`` as the editor reads it. Raises :class:`ListingMissing`
    when it has no ``listing.yaml``."""
    if not ListingDocuments(workspace).exists(name):
        raise ListingMissing(name)
    listing = workspace.load_listing(name)
    etsy_listing_id, printify_product_id = remote_ids(workspace, name)
    etsy_state = _etsy_state(etsy_states, etsy_listing_id)
    published = is_live_etsy_state(etsy_state)
    return _describe(
        workspace,
        WorkspaceFacts.gather(workspace),
        listing,
        name=name,
        listing_dir=workspace.listing_dir(name),
        published=published,
        status=workspace_listing_status(
            workspace, name, live=published, lifecycle=listing.lifecycle, etsy_state=etsy_state
        ),
        # The table's row gestures, so the editor's action row offers the
        # same lifecycle actions without deciding them itself.
        gestures=listing_gestures(
            lifecycle=listing.lifecycle, etsy_state=etsy_state, published=published
        ),
        modified_at=datetime.fromtimestamp(workspace.listing_file(name).stat().st_mtime, tz=UTC),
        etsy_listing_id=etsy_listing_id,
        printify_product_id=printify_product_id,
    )


def describe_draft(workspace: Workspace, document: Mapping[str, Any]) -> ListingView:
    """A candidate listing with no name yet, written nowhere.

    One that validates is described as it stands -- incomplete but sound, with
    its real issues. One that will not is the *empty* draft beside its
    ``field_errors``: there is no previous state to echo, so the caller must
    prefer its own copy of the candidate to everything but the errors.
    """
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
        name="",
        listing_dir=workspace.draft_listing_dir(),
        published=False,
        status="draft",
        gestures=(),
        field_errors=field_errors,
    )


def list_listings(workspace: Workspace, *, etsy_states: EtsyStates) -> list[ListingRow]:
    """Every listing, with Etsy asked **once** for the whole table rather
    than once per row."""
    facts = WorkspaceFacts.gather(workspace)
    names = workspace.listing_names()
    ids = {name: remote_ids(workspace, name)[0] for name in names}
    states = etsy_states([i for i in ids.values() if i is not None])
    return [
        listing_row(
            workspace,
            name,
            etsy_state=states.get(listing_id) if (listing_id := ids[name]) is not None else None,
            facts=facts,
        )
        for name in names
    ]


def listing_row(
    workspace: Workspace,
    name: str,
    *,
    etsy_state: str | None,
    facts: WorkspaceFacts | None = None,
) -> ListingRow:
    """One table row, for a caller that already knows the listing's Etsy
    state -- the table, and a delete answering with the row it left."""
    facts = facts if facts is not None else WorkspaceFacts.gather(workspace)
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
    listing = workspace.load_listing(name)
    published = published if etsy_listing_id is not None else False
    description = workspace.resolve_description(listing.etsy.description)
    return ListingRow(
        name=name,
        listing=listing,
        status=workspace_listing_status(
            workspace, name, live=published, lifecycle=listing.lifecycle, etsy_state=etsy_state
        ),
        issues=_business_issues(
            workspace,
            facts,
            workspace.listing_dir(name),
            listing,
            published=published,
            description_ref_error=str(description.error) if description.error is not None else None,
        ),
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
    """The resolved plan's name, and one resolved price per size -- using the
    first enabled colour as representative, since the editor's price table
    has no per-colour axis. ``resolve`` finds the plan's ref from wherever
    its owner lives: a listing's directory or a listing template's. A plan
    that will not load prices as though there were none."""
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
    colour = priced.colors[0] if priced.colors else ""
    prices: list[PricedSize] = []
    for size in sizes:
        try:
            money = priced.resolved_price(colour, size, pricing_plan=plan)
        except KeyError:
            continue
        prices.append(PricedSize(size=size, amount=money))
    return plan_name, prices


def _etsy_state(etsy_states: EtsyStates, etsy_listing_id: int | None) -> str | None:
    if etsy_listing_id is None:
        return None
    return etsy_states([etsy_listing_id]).get(etsy_listing_id)


def _describe(
    workspace: Workspace,
    facts: WorkspaceFacts,
    listing: Listing,
    *,
    name: str,
    listing_dir: Path,
    published: bool,
    status: ListingStatus,
    gestures: Sequence[ListingGesture],
    modified_at: datetime | None = None,
    etsy_listing_id: int | None = None,
    printify_product_id: str | None = None,
    field_errors: dict[str, str] | None = None,
) -> ListingView:
    """A `Listing` as the editor reads it, whether or not it is on disk: the
    unnamed draft carries the same computed issues and resolved prices as a
    saved listing, or the editor would show one thing before the listing was
    named and another after."""
    description = workspace.resolve_description(listing.etsy.description)
    issues = _business_issues(
        workspace,
        facts,
        listing_dir,
        listing,
        published=published,
        description_ref_error=str(description.error) if description.error is not None else None,
    )
    plan_name, resolved_prices = pricing_summary(
        workspace,
        facts,
        listing,
        resolve=lambda ref: workspace.resolve_ref(ref, listing_dir=listing_dir),
    )
    return ListingView(
        name=name,
        listing=listing,
        status=status,
        issues=issues,
        gestures=tuple(gestures),
        description_composed=description.composed,
        design_content_hash=workspace.design_content_hash(listing.design, listing_dir=listing_dir),
        pricing_plan_name=plan_name,
        resolved_prices=resolved_prices,
        garment_profile=facts.garment_profile(listing.garment_profile),
        modified_at=modified_at,
        etsy_listing_id=etsy_listing_id,
        printify_product_id=printify_product_id,
        field_errors=field_errors or {},
    )


def _business_issues(
    workspace: Workspace,
    facts: WorkspaceFacts,
    listing_dir: Path,
    listing: Listing,
    *,
    published: bool,
    description_ref_error: str | None,
) -> list[Issue]:
    """*listing_dir* rather than a listing name, because the unnamed draft
    has no directory. A workspace-rooted ref resolves the same against any
    listing directory, so `Workspace.draft_listing_dir` answers for it
    exactly as a real one would."""
    return check_listing(
        listing,
        garment_profile=facts.garment_profile(listing.garment_profile),
        garment_profile_names=facts.garment_profile_names,
        design_paths=_resolve_design_paths(workspace, listing, listing_dir),
        templates=facts.templates,
        published=published,
        description_ref_error=description_ref_error,
        videos=facts.videos(listing, listing_dir),
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
