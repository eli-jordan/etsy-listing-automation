"""Which pricing plans a workspace has, which suit a garment, and a
starting plan generated from live costs.

Shared by both ways a listing is created: the listings editor's plan picker
(``GET /api/pricing-plans``) and the ``new`` wizard's. Both used to read this
from the wizard package, which took the server through its terminal prompts;
here, one interpretation serves both and each adapter renders the rows its
own way (module-structure plan, PR 6). The ``new`` wizard's "create a new
plan" is :func:`create_starting_pricing_plan` (PR 10).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import ValidationError

from etsy_listings.core.clients import fx_rate as fx_rates
from etsy_listings.core.clients.fx_rate import FxRate
from etsy_listings.core.clients.printify import unofficial_variant_costs
from etsy_listings.core.clients.printify.models import (
    Blueprint,
    PrintProvider,
    ShippingRates,
    VariantSet,
)
from etsy_listings.core.clients.printify.protocol import CatalogClient
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.config.money import Money
from etsy_listings.core.config.pricing_plan import PricingPlan
from etsy_listings.core.config.slug import slugify
from etsy_listings.core.workspace.workspace import Workspace


@dataclass(frozen=True)
class PricingPlanOption:
    """A loadable plan and whether it was built for the garment asked about."""

    path: Path
    plan: PricingPlan
    compatible: bool


def load_candidate_pricing_plans(workspace: Workspace) -> list[tuple[Path, PricingPlan]]:
    """Every discovered plan that actually loads. A plan that won't parse or
    fails currency validation is skipped, not fatal -- one broken file costs
    its own row, not the whole picker."""
    result: list[tuple[Path, PricingPlan]] = []
    for path in workspace.pricing_plan_files():
        try:
            result.append((path, workspace.load_pricing_plan(path)))
        except (ConfigLoadError, ValidationError):
            continue
    return result


def pricing_plan_options(
    plans: list[tuple[Path, PricingPlan]], garment_profile: str
) -> list[PricingPlanOption]:
    """``plans``, those declaring exactly this garment profile first, each
    group by file stem, case-insensitively.

    An *exact* ``plan.garment_profile == garment_profile`` match: a plan
    declares its garment directly, so nothing is inferred. An empty
    ``garment_profile`` -- a listing that has not chosen one yet -- therefore
    marks no plan that names a garment.
    """
    options = [
        PricingPlanOption(path=path, plan=plan, compatible=plan.garment_profile == garment_profile)
        for path, plan in plans
    ]
    options.sort(key=lambda option: (not option.compatible, option.path.stem.lower()))
    return options


def pricing_plan_ref(plan_path: Path, *, root: Path) -> str:
    """The write-side counterpart to :meth:`Workspace.resolve_ref` -- a
    workspace-rooted POSIX ref, e.g. ``'pricing-plans/tee-basic.yaml'``
    (ADR-0046). Needed because discovery under ``pricing-plans/`` allows
    nesting, so the ref can't be hardcoded the way ``designs/{name}.png``
    is."""
    return plan_path.resolve().relative_to(root.resolve()).as_posix()


PORTAL_VERIFICATION_NOTE = (
    "Verify current costs on Printify's own portal: open this blueprint in "
    "the product catalog, choose the print provider manually, and check the "
    '"Product variants" tab\'s Price column.'
)


def compute_starting_prices(
    *,
    sizes: list[str],
    variant_set: VariantSet,
    variant_costs: dict[int, int],
    shipping: ShippingRates,
    fx_rate: FxRate | None,
    target_currency: str,
    margin_multiplier: Decimal = Decimal("1.10"),
) -> tuple[dict[str, Money], list[str]]:
    """size -> starting ``Money``, plus human-readable note lines for the
    generated file's comment block. Never raises -- every failure mode
    (missing cost, missing shipping, no fx rate) degrades to a 0-price entry
    and a note explaining why.

    Manufacturing + shipping cost is per (colour, size) variant, but a plan
    has no colour axis: usually every colour offering a size costs the same,
    so that shared figure is used; where colours disagree, the max is used
    and the disagreement is called out in the notes, so the generated file
    is honest about the simplification.
    """
    prices: dict[str, Money] = {}
    notes: list[str] = [PORTAL_VERIFICATION_NOTE, ""]
    for size in sizes:
        totals_cents: dict[str, int] = {}
        missing_colours: list[str] = []
        for variant in variant_set.variants:
            if variant.options.size != size:
                continue
            mfg = variant_costs.get(variant.id)
            ship = shipping.first_item_cost_cents(variant.id)
            if mfg is None or ship is None:
                missing_colours.append(variant.options.color)
                continue
            totals_cents[variant.options.color] = mfg + ship

        if missing_colours:
            notes.append(
                f"{size}: no cost/shipping data for colour(s) "
                f"{', '.join(sorted(missing_colours))} -- excluded from the calculation"
            )
        if not totals_cents:
            prices[size] = Money(Decimal(0), target_currency)
            notes.append(f"{size}: no cost data available at all -- priced at 0, fill in manually")
            continue

        distinct = set(totals_cents.values())
        chosen_cents = max(distinct)
        if len(distinct) > 1:
            breakdown = ", ".join(
                f"{colour}=${cents / 100:.2f}" for colour, cents in sorted(totals_cents.items())
            )
            notes.append(f"{size}: cost varies by colour ({breakdown}); using the max")

        usd_amount = (Decimal(chosen_cents) / Decimal(100)) * margin_multiplier
        if fx_rate is None:
            prices[size] = Money(Decimal(0), target_currency)
            notes.append(
                f"{size}: cost+shipping+margin is ${usd_amount:.2f} USD, but no FX rate could "
                f"be fetched -- priced at 0, fill in manually using "
                f"today's USD->{target_currency} rate"
            )
            continue

        converted = (usd_amount * fx_rate.rate).quantize(Decimal("0.01"))
        prices[size] = Money(converted, target_currency)
        notes.append(
            f"{size}: (${chosen_cents / 100:.2f} cost+shipping) x {margin_multiplier} margin "
            f"x {fx_rate.rate} {target_currency}/USD ({fx_rate.source}, "
            f"{fx_rate.fetched_at.isoformat()}) = {converted} {target_currency}"
        )
    return prices, notes


def write_pricing_plan(
    workspace: Workspace,
    name: str,
    garment_profile_slug: str,
    prices: dict[str, Money],
    notes: list[str],
) -> Path:
    """Writes ``pricing-plans/{slugify(name)}.yaml``, refusing to overwrite
    (as ``ListingDocuments.create`` refuses a taken name). ``price_overrides``
    is written empty -- the wizard never guesses a per-colour markup, only
    the flat table."""
    path = workspace.pricing_plans_dir() / f"{slugify(name)}.yaml"
    if path.is_file():
        raise FileExistsError(f"a pricing plan already exists at {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "\n".join(
        [
            "# Generated by `new` -- a starting point, not a final price. Formula",
            "# per size: (manufacturing cost + shipping cost) x 1.10 margin,",
            "# converted from USD at a one-off live FX rate. Adjust these numbers.",
            "#",
            *(f"# {line}" if line else "#" for line in notes),
        ]
    )
    body = yaml.safe_dump(
        {
            "garment_profile": garment_profile_slug,
            "prices": {size: str(price) for size, price in prices.items()},
            "price_overrides": {},
        },
        sort_keys=False,
    )
    path.write_text(f"{header}\n{body}", encoding="utf-8")
    return path


@dataclass(frozen=True)
class StartingPricingPlan:
    path: Path
    complete: bool
    """False when live costs or the FX rate could not be had, so some sizes
    fell back to 0 -- the file's comment block says which."""


def create_starting_pricing_plan(
    workspace: Workspace,
    catalog: CatalogClient,
    *,
    name: str,
    garment_profile_slug: str,
    blueprint: Blueprint,
    provider: PrintProvider,
    variant_set: VariantSet,
    sizes: list[str],
    fetch_costs: Callable[[int, int], dict[int, int]] | None = None,
    fetch_rate: Callable[[str], FxRate | None] | None = None,
) -> StartingPricingPlan:
    """Write ``pricing-plans/{slugify(name)}.yaml`` priced from today's costs.

    Manufacturing costs come from Printify's undocumented endpoint and the
    rate from a one-off FX fetch; both are fail-soft, so a plan is always
    written and :attr:`StartingPricingPlan.complete` says whether it is all
    real numbers. Shipping comes from the documented catalog. Refuses with
    ``FileExistsError`` to overwrite a plan. The fetches default to the live
    ones, looked up at call time.
    """
    costs_for = fetch_costs or unofficial_variant_costs.fetch_variant_costs
    rate_for = fetch_rate or fx_rates.fetch_usd_to
    currency = workspace.defaults.etsy.currency
    costs = costs_for(blueprint.id, provider.id)
    shipping = catalog.shipping(blueprint.id, provider.id)
    rate = rate_for(currency)
    prices, notes = compute_starting_prices(
        sizes=sizes,
        variant_set=variant_set,
        variant_costs=costs,
        shipping=shipping,
        fx_rate=rate,
        target_currency=currency,
    )
    path = write_pricing_plan(workspace, name, garment_profile_slug, prices, notes)
    return StartingPricingPlan(path=path, complete=bool(costs) and rate is not None)
