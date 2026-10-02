"""The operations behind ``new``, called directly: no prompt, no terminal.

Recording a garment profile, generating a starting pricing plan from live
costs, and which colours a new listing sells. The catalog is the fake, and
the two fail-soft live fetches arrive as arguments (module-structure plan,
PR 10). The wizard's question order, rows and exits are
``test_new_picker.py``'s and ``test_new.py``'s.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import yaml

from etsy_listings.core.application import garment_profiles, pricing_plans
from etsy_listings.core.clients.fx_rate import FxRate
from etsy_listings.core.clients.printify.fakes import FakeCatalogClient
from etsy_listings.core.clients.printify.models import (
    Blueprint,
    PrintAreaPlaceholder,
    PrintProvider,
    ShippingCost,
    ShippingProfile,
    ShippingRates,
    Variant,
    VariantOptions,
    VariantSet,
)
from etsy_listings.core.config.money import Money
from etsy_listings.core.workspace.workspace import Workspace

TEE = Blueprint(id=12, title="Unisex Heavy Cotton Tee", brand="Gildan", model="5000")
PROVIDER = PrintProvider(id=29, title="Monster Digital")
FRONT = (PrintAreaPlaceholder(position="front", width=4500, height=5400),)
VARIANTS = VariantSet(
    variants=(
        Variant(
            id=1,
            title="Black / S",
            options=VariantOptions(color="Black", size="S"),
            placeholders=FRONT,
        ),
        Variant(
            id=2,
            title="Black / M",
            options=VariantOptions(color="Black", size="M"),
            placeholders=FRONT,
        ),
    )
)
SHIPPING = ShippingRates(
    profiles=(
        ShippingProfile(
            variant_ids=(1, 2),
            first_item=ShippingCost(currency="USD", cost=500),
            additional_items=ShippingCost(currency="USD", cost=200),
        ),
    )
)
RATE = FxRate(rate=Decimal("10"), source="test", fetched_at=datetime(2026, 3, 1, tzinfo=UTC))


def _catalog() -> FakeCatalogClient:
    return FakeCatalogClient(
        [TEE],
        {TEE.id: [PROVIDER]},
        {(TEE.id, PROVIDER.id): VARIANTS},
        {(TEE.id, PROVIDER.id): SHIPPING},
    )


# ------------------------------------------------------------ garment profile


def test_a_first_use_records_the_garment_profile(workspace_root: Path) -> None:
    workspace = Workspace.discover(root_override=workspace_root)

    saved = garment_profiles.ensure_garment_profile(workspace, TEE, PROVIDER, VARIANTS)

    assert saved.slug == "gildan-5000"
    assert saved.written
    assert workspace.garment_profile_file("gildan-5000").is_file()
    assert saved.profile.sizes == ["S", "M"]
    assert saved.profile.print_area.width == 4500


def test_an_existing_garment_profile_is_reused_as_edited(workspace_root: Path) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    first = garment_profiles.ensure_garment_profile(workspace, TEE, PROVIDER, VARIANTS)
    path = workspace.garment_profile_file(first.slug)
    edited = yaml.safe_load(path.read_text(encoding="utf-8"))
    edited["colors"] = {"black": "dark"}
    path.write_text(yaml.safe_dump(edited), encoding="utf-8")

    again = garment_profiles.ensure_garment_profile(workspace, TEE, PROVIDER, VARIANTS)

    assert not again.written
    assert again.profile.colors == {"black": "dark"}


def test_a_new_listing_sells_the_profile_colours_else_every_catalog_colour(
    workspace_root: Path,
) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    saved = garment_profiles.ensure_garment_profile(workspace, TEE, PROVIDER, VARIANTS)

    assert garment_profiles.listing_colours(saved.profile, {"Black": "black"}) == ["black"]
    hand_edited = saved.profile.model_copy(update={"colors": {"navy": "dark", "ash": "light"}})
    assert garment_profiles.listing_colours(hand_edited, {"Black": "black"}) == ["ash", "navy"]


# ---------------------------------------------------- starting pricing plan


def test_a_starting_plan_is_priced_from_live_costs(workspace_root: Path) -> None:
    workspace = Workspace.discover(root_override=workspace_root)

    created = pricing_plans.create_starting_pricing_plan(
        workspace,
        _catalog(),
        name="Launch Low",
        garment_profile_slug="gildan-5000",
        blueprint=TEE,
        provider=PROVIDER,
        variant_set=VARIANTS,
        sizes=["S", "M"],
        fetch_costs=lambda blueprint_id, provider_id: {1: 1000, 2: 1000},
        fetch_rate=lambda currency: RATE,
    )

    assert created.path == workspace.pricing_plans_dir() / "launch-low.yaml"
    assert created.complete
    plan = workspace.load_pricing_plan(created.path)
    currency = workspace.defaults.etsy.currency
    # (10.00 cost + 5.00 shipping) x 1.10 margin x 10 = 165.00
    assert plan.prices["S"] == Money(Decimal("165.00"), currency)


def test_missing_live_data_still_writes_a_plan_and_says_so(workspace_root: Path) -> None:
    workspace = Workspace.discover(root_override=workspace_root)

    created = pricing_plans.create_starting_pricing_plan(
        workspace,
        _catalog(),
        name="fallback",
        garment_profile_slug="gildan-5000",
        blueprint=TEE,
        provider=PROVIDER,
        variant_set=VARIANTS,
        sizes=["S", "M"],
        fetch_costs=lambda blueprint_id, provider_id: {},
        fetch_rate=lambda currency: None,
    )

    assert not created.complete
    plan = workspace.load_pricing_plan(created.path)
    assert all(price.amount == 0 for price in plan.prices.values())
