"""Pure logic behind the ``new`` picker (PRD 19): everything that doesn't touch
a terminal, so it's testable through the fake catalog client with no
interactive prompting -- ``newcmd/interactive.py`` only sequences the
questions, and ``prompts.py`` picks a backend that can actually drive
the terminal it was given.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import ValidationError

from etsy_listings.clients.printify.models import Blueprint, ShippingRates, VariantSet
from etsy_listings.clients.printify.resolve import normalise
from etsy_listings.config.errors import ConfigLoadError, format_validation_error
from etsy_listings.config.garment_profile import BlueprintRef, GarmentProfile, PrintArea
from etsy_listings.config.listing import GENERATE, MAX_MEDIA_ENTRIES, Listing
from etsy_listings.config.money import Money
from etsy_listings.config.pricing_plan import PricingPlan
from etsy_listings.config.slug import ColourExceptions, slug_map, slugify
from etsy_listings.newcmd.fx_rate import FxRate
from etsy_listings.workspace.workspace import Workspace

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "tshirt": ("t-shirt", "tee", "shirt"),
}
"""PRD: the catalog endpoint exposes no category facet, so filtering is
client-side keyword matching over title/brand/model -- flagged in the PRD as
something to verify for a better mechanism; unchanged here (risk 7)."""

SIZE_ORDER = ["XS", "S", "M", "L", "XL", "XXL", "2XL", "XXXL", "3XL", "4XL", "5XL", "6XL"]
"""Both spellings of the big sizes, adjacent, because Printify uses the
numeric one. Comfort Colors 1717 / Monster Digital sells ``2XL``/``3XL``, and
with only ``XXL``/``XXXL`` listed here they fell through to the alphabetical
"unknown" tail while ``4XL`` sorted normally -- producing
``S M L XL 4XL 2XL 3XL`` in the garment profile `new` wrote."""


def filter_blueprints_by_category(blueprints: list[Blueprint], category: str) -> list[Blueprint]:
    keywords = CATEGORY_KEYWORDS.get(category, (category,))
    keywords_lower = tuple(kw.lower() for kw in keywords)

    def matches(blueprint: Blueprint) -> bool:
        haystack = f"{blueprint.title} {blueprint.brand} {blueprint.model}".lower()
        return any(keyword in haystack for keyword in keywords_lower)

    return [b for b in blueprints if matches(b)]


# ----------------------------------------------------------------------
# The garment picker's rows.
#
# Printify offers hundreds of blueprints and `--category tshirt` still leaves
# dozens, so the rows are columned -- marker, brand, model, title -- and the
# ones this workspace already has a garment profile for sort to the top. Building them
# lives here rather than in the prompt so it can be tested without a terminal,
# the same reason every other decision in `new` does. Filtering, on a terminal
# that can do it at all, is fzf's job -- see `prompts.py`.
# ----------------------------------------------------------------------

LOCAL_MARKER = "⭐"
LOCAL_MARKER_FALLBACK = "* "
"""Two terminal columns either way -- ``⭐`` is East Asian Wide, so it occupies
the same width as the two-character ASCII fallback and the marker column stays
aligned on a terminal that cannot print it."""

MARKER_WIDTH = 2


@dataclass(frozen=True)
class Choice[T]:
    """One row of a picker: the thing itself, and the text offered for it.

    Three of these existed -- ``BlueprintChoice``, ``DesignChoice``,
    ``PricingPlanChoice`` -- each holding a domain object, a flag, and a
    rendered label, and each with its own builder doing the same three steps.
    The picker only ever reads ``label`` (to offer it) and ``value`` (to act on
    the answer), so the per-type fields were paid for and never spent.
    """

    value: T
    label: str
    marked: bool = False
    """Whether this row is called out, and why is the picker's business: a
    garment already used in this workspace, a plan whose sizes match, a design
    that already has a listing. The *rendering* of the callout differs (a
    marker column, a trailing note) and so does whether it sorts first, which
    is why those stay with each picker rather than moving in here."""


def marked_choices[T](
    items: Iterable[T],
    *,
    marked: Callable[[T], bool],
    sort_key: Callable[[T], Any],
    label: Callable[[T], str],
    marker: str = LOCAL_MARKER,
) -> list[Choice[T]]:
    """Rows with the marked ones first, each label behind an aligned marker column.

    The shape both "which of these have I used before?" pickers want: mark,
    sort marked-first then by the picker's own key, and reserve the marker
    column on every row so the columns after it line up whether or not the row
    carries one.
    """
    entries = [(item, marked(item)) for item in items]
    entries.sort(key=lambda entry: (not entry[1], sort_key(entry[0])))
    return [
        Choice(
            value=item,
            marked=is_marked,
            label=f"{marker if is_marked else ' ' * MARKER_WIDTH}  {label(item)}",
        )
        for item, is_marked in entries
    ]


def local_blueprint_keys(workspace: Workspace) -> set[tuple[str, str]]:
    """The ``(brand, model)`` pairs this workspace already has a garment
    profile for, normalised for comparison.

    Keyed on brand+model rather than title, because that is what a garment
    profile now identifies a blueprint by (PRD 23) -- and it is what makes
    the marker survive Printify retitling a garment.

    A garment profile that will not parse is skipped rather than fatal: it
    costs a row its marker, and refusing to open the picker over one
    unrelated broken file would be a poor trade.
    """
    keys: set[tuple[str, str]] = set()
    for name in workspace.garment_profile_names():
        try:
            ref = workspace.load_garment_profile(name).blueprint
        except (ConfigLoadError, ValidationError):
            continue
        keys.add((normalise(ref.brand), normalise(ref.model)))
    return keys


def build_blueprint_choices(
    blueprints: list[Blueprint],
    local_keys: set[tuple[str, str]],
    *,
    marker: str = LOCAL_MARKER,
) -> list[Choice[Blueprint]]:
    """Blueprints as aligned ``marker  brand  model  title`` rows.

    Brand and model are what identify a garment to anyone who buys blanks --
    "Gildan 18500" is the thing you look up, while Printify's titles bury it
    ("Unisex Pullover Hoodie" is sold under half a dozen brands). Garments
    this workspace already has a garment profile for come first and carry the marker:
    in practice a shop reuses a handful of blueprints over and over, and
    having to re-find the one used yesterday is the picker failing at its most
    common job. Within each group, rows sort by brand then title, so the brand
    column reads as blocks rather than as noise.
    """
    brand_width = max((len(b.brand) for b in blueprints), default=0)
    model_width = max((len(b.model) for b in blueprints), default=0)
    return marked_choices(
        blueprints,
        marked=lambda b: (normalise(b.brand), normalise(b.model)) in local_keys,
        sort_key=lambda b: (b.brand.lower(), b.title.lower()),
        label=lambda b: f"{b.brand.ljust(brand_width)}  {b.model.ljust(model_width)}  {b.title}",
        marker=marker,
    )


def sort_sizes(sizes: set[str]) -> list[str]:
    known = [s for s in SIZE_ORDER if s in sizes]
    unknown = sorted(sizes - set(SIZE_ORDER))
    return known + unknown


def resolve_colour_slugs(variant_set: VariantSet, exceptions: ColourExceptions) -> dict[str, str]:
    """Colour name -> slug, applying exceptions.yaml and raising on collision
    (PRD: "new reports any collisions it finds while building a garment profile")."""
    return slug_map(variant_set.colors, exceptions)


def garment_profile_slug_for(blueprint: Blueprint) -> str:
    """``garment-profiles/{slug}.yaml``, from brand and model.

    Not from the title: Printify's is generic, so a title slug would file the
    Comfort Colors 1717 under ``unisex-garment-dyed-t-shirt.yaml`` alongside
    every other brand's version of the same shirt. Brand and model give
    ``comfort-colors-1717`` -- the name the docs have always shown, and one
    that survives a retitle.
    """
    return slugify(f"{blueprint.brand} {blueprint.model}")


def blueprint_ref(blueprint: Blueprint) -> BlueprintRef:
    """The catalog entry as a garment profile records it (PRD 23).

    Brand and model are written verbatim, ® and all, because that is what the
    catalog says; resolution normalises both sides, so a human editing the
    file afterwards need not reproduce the symbol.
    """
    return BlueprintRef(brand=blueprint.brand, model=blueprint.model, title=blueprint.title)


def build_garment_profile(
    *,
    blueprint: Blueprint,
    provider_title: str,
    placeholder: str,
    variant_set: VariantSet,
    colors: dict[str, Literal["light", "dark"]] | None = None,
) -> GarmentProfile:
    ref = blueprint_ref(blueprint)
    area = variant_set.placeholder(placeholder)
    if area is None:
        available = ", ".join(variant_set.positions()) or "(none)"
        raise ValueError(
            f"blueprint {str(ref)!r} / provider {provider_title!r} has no "
            f"{placeholder!r} placeholder. Available: {available}"
        )
    sizes = sort_sizes({v.options.size for v in variant_set.variants})
    return GarmentProfile(
        blueprint=ref,
        print_provider=provider_title,
        placeholder=placeholder,
        print_area=PrintArea(width=area.width, height=area.height),
        sizes=sizes,
        colors=colors or {},
    )


# ----------------------------------------------------------------------
# The design picker's rows.
#
# `new` is a wizard, so the design it builds a listing for is picked from
# what is on disk rather than typed -- the same reasoning that moved the
# mockup template off a typed name. Ordering is by modification time,
# newest first: artwork is made minutes before the listing that ships it, so
# the design you want is nearly always the one you just saved.
# ----------------------------------------------------------------------


def build_design_choices(paths: list[Path], listing_names: set[str]) -> list[Choice[Path]]:
    """Designs as ``date  name`` rows, newest first.

    The date is in the row rather than implied by the order because "newest
    first" is invisible otherwise -- and fzf reorders the rows the moment a
    query is typed, at which point the only thing still saying how fresh a
    design is, is the row itself. Ties (a batch exported in one go all carry
    the same second) break on name, so the order is stable rather than
    filesystem-dependent.

    A design that already has a listing is marked: ``new`` refuses to
    overwrite one (:func:`write_listing`), so the row would otherwise look
    like a choice and behave like a dead end. Marked as a trailing note rather
    than through :func:`marked_choices` -- this callout is a warning, and
    sorting warnings to the top would be exactly wrong.
    """
    entries = sorted(
        ((path, path.stat().st_mtime) for path in paths),
        key=lambda entry: (-entry[1], entry[0].stem.lower()),
    )
    return [
        Choice(
            value=path,
            marked=path.stem in listing_names,
            label=(
                f"{datetime.fromtimestamp(modified):%Y-%m-%d %H:%M}  {path.stem}"
                f"{'  (listing exists)' if path.stem in listing_names else ''}"
            ),
        )
        for path, modified in entries
    ]


def write_garment_profile_if_absent(
    workspace: Workspace, slug: str, garment_profile: GarmentProfile
) -> bool:
    """Returns True if a new garment profile was written, False if one already
    existed and was left untouched (PRD: "writes garment-profiles/{slug}.yaml
    if absent; reuses it silently if present")."""
    path = workspace.garment_profile_file(slug)
    if path.is_file():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(garment_profile.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    return True


def load_template_kind(workspace: Workspace, template: str) -> str:
    """Which of the three kinds ``template`` is (`A11`).

    ``new`` has to know: the shape of a valid ``media`` entry depends on it,
    and writing the wrong shape produces a listing that only fails later, at
    render time, with nothing pointing back at ``new``.
    """
    return workspace.load_template_config(template).kind


def build_media_entries(*, template: str, kind: str, colours: list[str]) -> list[dict[str, str]]:
    """The stub's ``media:``, which depends on the referenced template's kind.

    ``colour-matrix`` gets one entry per colour, each naming its colour --
    but capped at Etsy's 20-image limit, because a print provider can offer
    far more colours than Etsy accepts photos: Comfort Colors 1717 / Monster
    Digital offers 33, and one entry each is a listing Etsy will reject.
    Which 20 is genuinely arbitrary, so it is the first 20 in offer order and
    ``new`` says that it truncated. Every colour still appears in ``colors:``
    -- that decides which Printify variants sell, not which photos get
    rendered (PRD 31).

    ``multiple`` and ``single`` get exactly one entry and **no** ``colour``:
    each produces one output, so there is nothing to disambiguate (PRD 28).
    """
    if kind == "colour-matrix":
        return [{"template": template, "colour": colour} for colour in colours[:MAX_MEDIA_ENTRIES]]
    return [{"template": template}]


# ----------------------------------------------------------------------
# Pricing plans (PRD 33-36): the picker's rows, the "create new plan" cost
# calculation, and writing the resulting file. Pure logic only -- terminal
# sequencing lives in newcmd/interactive.py, the same split as everything
# else in this module.
# ----------------------------------------------------------------------

CREATE_NEW_PLAN_LABEL = "+ create a new pricing plan"

PORTAL_VERIFICATION_NOTE = (
    "Verify current costs on Printify's own portal: open this blueprint in "
    "the product catalog, choose the print provider manually, and check the "
    '"Product variants" tab\'s Price column.'
)


def load_candidate_pricing_plans(workspace: Workspace) -> list[tuple[Path, PricingPlan]]:
    """Every discovered plan that actually loads. A plan that won't parse or
    fails currency validation is skipped, not fatal -- same precedent as
    :func:`local_blueprint_keys` skipping a broken garment profile."""
    result: list[tuple[Path, PricingPlan]] = []
    for path in workspace.pricing_plan_files():
        try:
            result.append((path, workspace.load_pricing_plan(path)))
        except (ConfigLoadError, ValidationError):
            continue
    return result


def build_pricing_plan_choices(
    plans: list[tuple[Path, PricingPlan]],
    garment_profile_slug: str,
    *,
    marker: str = LOCAL_MARKER,
) -> list[Choice[Path]]:
    """Rows for the picker: plans declaring this exact garment profile sort
    first and carry the marker -- an *exact*
    ``plan.garment_profile == garment_profile_slug`` match, since a plan
    declares its garment directly (PRD 33), unlike the blueprint picker's
    marker, which infers "already used here"."""
    compatible = {path for path, plan in plans if plan.garment_profile == garment_profile_slug}
    return marked_choices(
        [path for path, _ in plans],
        marked=lambda path: path in compatible,
        sort_key=lambda path: path.stem.lower(),
        label=lambda path: path.stem,
        marker=marker,
    )


def pricing_plan_ref(plan_path: Path, *, listing_dir: Path) -> str:
    """The write-side counterpart to :meth:`Workspace.resolve` -- a
    ``listing_dir``-relative POSIX ref, e.g.
    ``'../../pricing-plans/tee-basic.yaml'``. Needed because (unlike
    ``design``/``garment_profile``, which have one fixed depth) discovery under
    ``pricing-plans/`` allows nesting, so the ref can't be hardcoded the way
    ``../../designs/{name}.png`` is."""
    return plan_path.resolve().relative_to(listing_dir.resolve(), walk_up=True).as_posix()


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
    and a note explaining why (PRD 35/36).

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
    (mirrors :func:`write_listing`). ``price_overrides`` is written empty --
    the wizard never guesses a per-colour markup, only the flat table."""
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


def build_listing_stub(
    *,
    garment_profile_slug: str,
    design_ref: str,
    colours: list[str],
    pricing_plan_ref: str,
    brief: str,
    media: list[dict[str, str]],
) -> dict[str, Any]:
    """A starting ``listing.yaml`` document: prices come from the referenced
    pricing plan (per-size/per-colour adjustment is a manual edit, PRD step
    2), the media entries :func:`build_media_entries` decided, blank title and
    description fields, and a ``<generate>`` sentinel for tags."""
    return {
        "garment_profile": garment_profile_slug,
        "design": design_ref,
        "colors": colours,
        "brief": brief,
        "pricing_plan": pricing_plan_ref,
        "prices": {},
        "etsy": {"title": "", "description": "", "tags": GENERATE},
        "media": media,
    }


def validate_listing_stub(data: dict[str, Any], *, currency: str) -> Listing:
    try:
        return Listing.model_validate(data, context={"currency": currency})
    except ValidationError as exc:
        raise format_validation_error(Path("<new listing stub>"), exc) from exc


def write_listing(workspace: Workspace, design_name: str, data: dict[str, Any]) -> Path:
    path = workspace.listing_file(design_name)
    if path.is_file():
        raise FileExistsError(f"a listing already exists at {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path
