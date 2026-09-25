"""`new`, walked end to end on the backend a cygwin pty actually gets.

The plain-`input()` selector, not the prompt double: the wizard's *sequencing*
is what `tests/behaviour/test_new_picker.py` covers through `scripted`, and
what this file adds is that the whole thing survives the one backend that has
to keep working when neither fzf nor prompt_toolkit can run (CLAUDE.md, "the
cygwin pty is not a Windows console").
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings import prompts
from etsy_listings.clients.printify.models import Blueprint
from etsy_listings.workspace.workspace import Workspace

from tests.support.doubles import replies

GILDAN_TEE = Blueprint(id=12, title="Unisex Heavy Cotton Tee", brand="Gildan", model="5000")


def _one_garment_catalog():
    """One blueprint, one provider, one colour in two sizes -- enough to walk
    `new` end to end without a network. Carries an (empty) shipping fixture too
    -- the pricing-plan picker's "create new" flow always calls
    `catalog.shipping()`, and the fake raises on an unfixtured key rather than
    degrading, unlike the real fail-soft cost/FX fetches."""
    from etsy_listings.clients.printify.fakes import FakeCatalogClient
    from etsy_listings.clients.printify.models import (
        PrintAreaPlaceholder,
        PrintProvider,
        ShippingCost,
        ShippingProfile,
        ShippingRates,
        Variant,
        VariantOptions,
        VariantSet,
    )

    front = (PrintAreaPlaceholder(position="front", width=4500, height=5400),)
    return FakeCatalogClient(
        [GILDAN_TEE],
        {GILDAN_TEE.id: [PrintProvider(id=29, title="Monster Digital")]},
        {
            (GILDAN_TEE.id, 29): VariantSet(
                variants=(
                    Variant(
                        id=1,
                        title="Black / S",
                        options=VariantOptions(color="Black", size="S"),
                        placeholders=front,
                    ),
                    Variant(
                        id=2,
                        title="Black / M",
                        options=VariantOptions(color="Black", size="M"),
                        placeholders=front,
                    ),
                ),
            )
        },
        {
            (GILDAN_TEE.id, 29): ShippingRates(
                profiles=(
                    ShippingProfile(
                        variant_ids=(1, 2),
                        first_item=ShippingCost(currency="USD", cost=500),
                        additional_items=ShippingCost(currency="USD", cost=200),
                    ),
                )
            )
        },
    )


def _no_network_pricing_plan_generation(monkeypatch) -> None:
    """The "create new pricing plan" flow always calls the undocumented cost
    endpoint and a live FX API -- neither may run in a test. Both are
    fail-soft by design, so stubbing them to "no data" still produces a
    usable (all-zero-price) plan, matching the flow's own guarantees."""
    from etsy_listings.newcmd import fx_rate, unofficial_variant_costs

    monkeypatch.setattr(unofficial_variant_costs, "fetch_variant_costs", lambda *a, **k: {})
    monkeypatch.setattr(fx_rate, "fetch_usd_to", lambda *a, **k: None)


NEW_WIZARD: dict[str, object] = {
    "Garment": "Gildan",
    "Print provider": "Monster Digital",
    "Mockup template set": "flat-lay-01",
    "Pricing plan": "create a new",
    "Pricing plan name": "launch-low",
}
"""Answers to every question `new` asks on its main path, keyed by what it
asked rather than by when.

Not listed, because it is not on that path: `Design`, asked only when no
design name was given. A test that wants it adds its own key. Light-vs-dark
artwork tone is never asked by `new` at all -- it is a hand-edit to the
generated garment profile (docs/multi-placement-rendering.md).

The two pricing keys look ambiguous and are not: a fragment that is the whole
question wins outright, and otherwise the longest match does, so "Pricing plan
name:" takes the second and the bare "Pricing plan" picker takes the first.
See ``tests/support/scripted.py``.
"""


def _ordinal(rows: list[str], wanted: str) -> str:
    """``wanted``'s answer in the plain-input backend: its 1-based position.

    Derived rather than written down. A literal ``"2"`` means `flat-lay-01`
    only while it happens to be second in the fixture workspace's template
    list; add a template and every later reply shifts by one, so the run
    answers questions it was never meant to and fails somewhere that has
    nothing to do with the cause.
    """
    return str(rows.index(wanted) + 1)


def test_new_runs_end_to_end_through_the_plain_input_backend(
    workspace_root: Path, monkeypatch
) -> None:
    """The one test that drives `new` through a prompt *backend*.

    Everything below answers `prompts.choose`/`text`/`confirm` directly, which
    is the seam for what `new` decides and writes. This one goes the whole way
    down: no fzf, no prompt_toolkit, so every question is a numbered list read
    off `input()` -- the path every cygwin session takes, and the reason the
    fallback exists at all. Answers are positions here because positions are
    genuinely that backend's interface.
    """
    from etsy_listings.newcmd.interactive import run_new

    monkeypatch.setattr(prompts, "fzf_command", lambda: None)
    monkeypatch.setattr(prompts, "prompt_toolkit_works", lambda: False)
    _no_network_pricing_plan_generation(monkeypatch)

    workspace = Workspace.discover(root_override=workspace_root)
    monkeypatch.setattr(
        "builtins.input",
        replies(
            [
                "1",  # Garment -- the fake catalog offers exactly one
                "1",  # Print provider -- likewise
                _ordinal(workspace.template_names(), "flat-lay-01"),
                "1",  # Pricing plan -- none on disk, so row 1 is "create a new"
                "launch-low",  # ...and its name
            ]
        ),
    )

    run_new(workspace, _one_garment_catalog(), "brand-new-design", "tshirt")

    listing = workspace_root / "listings" / "brand-new-design" / "listing.yaml"
    assert listing.is_file()
    assert "flat-lay-01" in listing.read_text(encoding="utf-8")
    assert (workspace_root / "garment-profiles" / "gildan-5000.yaml").is_file()
    assert (workspace_root / "pricing-plans" / "launch-low.yaml").is_file()


def test_new_writes_a_listing_that_validates_against_a_single_kind_template(
    workspace_root: Path, monkeypatch, scripted
) -> None:
    """A `single`-kind template has one output and no colour to name (PRD 28).
    `new` used to write one `{template, colour}` entry per colour regardless of
    kind, which is not a listing the renderer accepts."""
    from etsy_listings.config.listing import Listing
    from etsy_listings.newcmd.interactive import run_new

    _no_network_pricing_plan_generation(monkeypatch)
    _write_single_kind_template(workspace_root / "mockup-templates" / "lifestyle-01")
    scripted(
        {
            **NEW_WIZARD,
            "Mockup template set": "lifestyle-01",
            "Pricing plan name": "single-kind-plan",
        }
    )

    workspace = Workspace.discover(root_override=workspace_root)
    run_new(workspace, _one_garment_catalog(), "single-kind-design", "tshirt")

    listing = Listing.load(
        workspace_root / "listings" / "single-kind-design" / "listing.yaml", currency="NOK"
    )
    assert len(listing.media) == 1
    assert listing.media[0].template == "lifestyle-01"
    assert listing.media[0].colour is None


def test_new_can_generate_a_pricing_plan_from_fabricated_cost_data(
    workspace_root: Path, monkeypatch, scripted
) -> None:
    """The "create new pricing plan" flow end to end, with the two live
    fetches stubbed to deterministic (non-empty) data instead of the
    all-zero fail-soft path -- confirms the generated file and the listing's
    `pricing_plan:` ref actually agree, and that a real price shows up."""
    from datetime import UTC, datetime
    from decimal import Decimal

    from etsy_listings.config.listing import Listing
    from etsy_listings.config.money import Money
    from etsy_listings.newcmd import fx_rate, unofficial_variant_costs
    from etsy_listings.newcmd.fx_rate import FxRate
    from etsy_listings.newcmd.interactive import run_new

    monkeypatch.setattr(
        unofficial_variant_costs, "fetch_variant_costs", lambda *a, **k: {1: 1000, 2: 1000}
    )
    fixed_rate = FxRate(rate=Decimal("10"), source="test", fetched_at=datetime.now(UTC))
    monkeypatch.setattr(fx_rate, "fetch_usd_to", lambda *a, **k: fixed_rate)
    scripted({**NEW_WIZARD, "Pricing plan name": "computed-plan"})

    catalog = _one_garment_catalog()
    workspace = Workspace.discover(root_override=workspace_root)
    run_new(workspace, catalog, "priced-design", "tshirt")

    plan_path = workspace_root / "pricing-plans" / "computed-plan.yaml"
    assert plan_path.is_file()
    plan = workspace.load_pricing_plan(plan_path)
    assert plan.garment_profile == "gildan-5000"
    zero = Money.parse(f"0 {workspace.defaults.etsy.currency}")
    assert all(price != zero for price in plan.prices.values())  # real cost data was used

    listing = Listing.load(
        workspace_root / "listings" / "priced-design" / "listing.yaml", currency="NOK"
    )
    assert listing.pricing_plan == "pricing-plans/computed-plan.yaml"


def test_new_offers_an_existing_compatible_pricing_plan(
    workspace_root: Path, monkeypatch, scripted
) -> None:
    """A plan already on disk for this garment profile is picked straight
    from the list -- the wizard only needs to create one when none exist."""
    from etsy_listings.config.listing import Listing
    from etsy_listings.newcmd.interactive import run_new

    _no_network_pricing_plan_generation(monkeypatch)

    plans_dir = workspace_root / "pricing-plans"
    plans_dir.mkdir()
    (plans_dir / "existing.yaml").write_text(
        "garment_profile: gildan-5000\nprices:\n  S: 100 NOK\n  M: 100 NOK\n",
        encoding="utf-8",
    )
    script = scripted({**NEW_WIZARD, "Pricing plan": "existing"})

    workspace = Workspace.discover(root_override=workspace_root)
    run_new(workspace, _one_garment_catalog(), "reuses-a-plan", "tshirt")

    listing = Listing.load(
        workspace_root / "listings" / "reuses-a-plan" / "listing.yaml", currency="NOK"
    )
    assert listing.pricing_plan == "pricing-plans/existing.yaml"
    assert not (plans_dir / "reuses-a-plan.yaml").exists()  # nothing new was written
    # It was offered as a *compatible* plan, marked and sorted above the
    # create-new row -- which is what makes reusing it the obvious answer.
    assert script.rows_for("Pricing plan")[0].endswith("existing")
    assert "Pricing plan name:" not in script.asked, "it never reached the create-new branch"


def test_cancelling_the_pricing_plan_picker_stops_new(
    workspace_root: Path, monkeypatch, scripted
) -> None:
    from etsy_listings.newcmd.interactive import run_new

    scripted({**NEW_WIZARD, "Pricing plan": None})

    workspace = Workspace.discover(root_override=workspace_root)
    with pytest.raises(prompts.Cancelled):
        run_new(workspace, _one_garment_catalog(), "cancelled-at-pricing", "tshirt")

    assert not (workspace_root / "listings" / "cancelled-at-pricing").exists()


SINGLE_KIND_TEMPLATE = """\
kind: single
colour: white
artwork: on-light
bounding_box:
- {x: 10.0, y: 10.0}
- {x: 90.0, y: 10.0}
- {x: 90.0, y: 90.0}
- {x: 10.0, y: 90.0}
"""


def _write_single_kind_template(directory: Path) -> None:
    directory.mkdir(parents=True)
    (directory / "template.yaml").write_text(SINGLE_KIND_TEMPLATE, encoding="utf-8")


def test_cancelling_the_garment_picker_stops_new(workspace_root: Path, scripted) -> None:
    from etsy_listings.clients.printify.fakes import FakeCatalogClient
    from etsy_listings.newcmd.interactive import run_new

    scripted({**NEW_WIZARD, "Garment": None})

    workspace = Workspace.discover(root_override=workspace_root)
    with pytest.raises(prompts.Cancelled):
        run_new(workspace, FakeCatalogClient([GILDAN_TEE], {}, {}), "another-design", "tshirt")

    assert not (workspace_root / "listings" / "another-design").exists()
