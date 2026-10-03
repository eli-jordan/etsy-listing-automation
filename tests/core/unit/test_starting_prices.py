"""A starting pricing plan, called directly: the prices computed from
live costs and the file written for them. Moved from the `new` picker's
tests (test-suite quality plan, PR 9); the end-to-end operation is
``tests/core/behaviour/test_garment_operations.py``'s."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from etsy_listings.core.application.pricing_plans import (
    compute_starting_prices,
    write_pricing_plan,
)
from etsy_listings.core.clients.fx_rate import FxRate
from etsy_listings.core.clients.printify.models import (
    PrintAreaPlaceholder,
    ShippingCost,
    ShippingProfile,
    ShippingRates,
    Variant,
    VariantOptions,
    VariantSet,
)
from etsy_listings.core.config.money import Money
from etsy_listings.core.workspace.workspace import Workspace

SMALL_FRONT = (PrintAreaPlaceholder(position="front", width=3461, height=3955),)
LARGE_FRONT = (PrintAreaPlaceholder(position="front", width=4500, height=5400),)
"""Placeholders hang off each *variant*, and differ by garment size -- which is
what the real payload does. See `Variant.placeholders`."""
VARIANT_SET = VariantSet(
    variants=(
        Variant(
            id=1,
            title="Black / S",
            options=VariantOptions(color="Black", size="S"),
            placeholders=SMALL_FRONT,
        ),
        Variant(
            id=2,
            title="Black / M",
            options=VariantOptions(color="Black", size="M"),
            placeholders=LARGE_FRONT,
        ),
        Variant(
            id=3,
            title="Blue Jean / S",
            options=VariantOptions(color="Blue Jean", size="S"),
            placeholders=SMALL_FRONT,
        ),
        Variant(
            id=4,
            title="Blue Jean / M",
            options=VariantOptions(color="Blue Jean", size="M"),
            placeholders=LARGE_FRONT,
        ),
    ),
)


def test_write_pricing_plan_sets_profile_from_the_chosen_garment_profile(
    workspace_root: Path,
) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    prices = {"S": Money.parse("100 NOK")}

    path = write_pricing_plan(workspace, "Launch Low", "comfort-colors-1717", prices, ["a note"])

    assert path == workspace.pricing_plans_dir() / "launch-low.yaml"
    plan = workspace.load_pricing_plan(path)
    assert plan.garment_profile == "comfort-colors-1717"
    assert plan.prices == prices
    assert "a note" in path.read_text(encoding="utf-8")


def test_write_pricing_plan_refuses_to_overwrite(workspace_root: Path) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    prices = {"S": Money.parse("100 NOK")}
    write_pricing_plan(workspace, "dup", "comfort-colors-1717", prices, [])
    with pytest.raises(FileExistsError):
        write_pricing_plan(workspace, "dup", "comfort-colors-1717", prices, [])


def _shipping_rates(*, small_cents: int, medium_cents: int) -> ShippingRates:
    return ShippingRates(
        profiles=(
            ShippingProfile(
                variant_ids=(1, 3),
                first_item=ShippingCost(currency="USD", cost=small_cents),
                additional_items=ShippingCost(currency="USD", cost=small_cents),
            ),
            ShippingProfile(
                variant_ids=(2, 4),
                first_item=ShippingCost(currency="USD", cost=medium_cents),
                additional_items=ShippingCost(currency="USD", cost=medium_cents),
            ),
        )
    )


def test_compute_starting_prices_applies_margin_and_converts_currency() -> None:
    # variants 1 (Black/S) and 3 (Blue Jean/S) both cost 1000c mfg + 500c shipping.
    variant_costs = {1: 1000, 2: 1500, 3: 1000, 4: 1500}
    shipping = _shipping_rates(small_cents=500, medium_cents=600)
    rate = FxRate(rate=Decimal("10"), source="test", fetched_at=datetime.now(UTC))

    prices, notes = compute_starting_prices(
        sizes=["S", "M"],
        variant_set=VARIANT_SET,
        variant_costs=variant_costs,
        shipping=shipping,
        fx_rate=rate,
        target_currency="NOK",
    )

    # S: (10.00 + 5.00) * 1.10 = 16.50 USD * 10 = 165.00 NOK
    assert prices["S"] == Money.parse("165.00 NOK")
    # M: (15.00 + 6.00) * 1.10 = 23.10 USD * 10 = 231.00 NOK
    assert prices["M"] == Money.parse("231.00 NOK")
    assert any("S" in note for note in notes)


def test_compute_starting_prices_uses_the_max_when_colours_disagree() -> None:
    # Both size-S variants (1 and 3) get different manufacturing costs.
    variant_costs = {1: 1000, 3: 2000}
    shipping = _shipping_rates(small_cents=0, medium_cents=0)
    rate = FxRate(rate=Decimal("1"), source="test", fetched_at=datetime.now(UTC))

    prices, notes = compute_starting_prices(
        sizes=["S"],
        variant_set=VARIANT_SET,
        variant_costs=variant_costs,
        shipping=shipping,
        fx_rate=rate,
        target_currency="USD",
    )

    # max(1000, 2000) = 2000c = $20.00, * 1.10 margin = $22.00
    assert prices["S"] == Money.parse("22.00 USD")
    assert any("varies by colour" in note for note in notes)


def test_compute_starting_prices_is_fail_soft_with_no_cost_data() -> None:
    shipping = _shipping_rates(small_cents=500, medium_cents=600)

    prices, notes = compute_starting_prices(
        sizes=["S"],
        variant_set=VARIANT_SET,
        variant_costs={},  # the undocumented endpoint returned nothing
        shipping=shipping,
        fx_rate=FxRate(rate=Decimal("10"), source="test", fetched_at=datetime.now(UTC)),
        target_currency="NOK",
    )

    assert prices["S"] == Money.parse("0 NOK")
    assert any("no cost data" in note for note in notes)


def test_compute_starting_prices_is_fail_soft_with_no_fx_rate() -> None:
    variant_costs = {1: 1000, 3: 1000}
    shipping = _shipping_rates(small_cents=500, medium_cents=600)

    prices, notes = compute_starting_prices(
        sizes=["S"],
        variant_set=VARIANT_SET,
        variant_costs=variant_costs,
        shipping=shipping,
        fx_rate=None,  # the FX fetch failed
        target_currency="NOK",
    )

    assert prices["S"] == Money.parse("0 NOK")
    assert any("no FX rate" in note for note in notes)
