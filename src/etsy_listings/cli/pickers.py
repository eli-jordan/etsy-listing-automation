"""Picker rows for the ``new`` wizard: what each question offers, and how.

Printify offers hundreds of blueprints and ``--category tshirt`` still leaves
dozens, so rows are columned and called out. Building them lives here rather
than in the prompt so it can be tested without a terminal; *which* plans suit
a garment and which garments a workspace already has are core's answers
(``core/application/pricing_plans.py``, ``garment_profiles.py``) -- only the
rendering is the wizard's. Filtering, on a terminal that can do it at all, is
fzf's job -- see :mod:`etsy_listings.cli.prompts`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from etsy_listings.core.application.pricing_plans import pricing_plan_options
from etsy_listings.core.clients.printify.models import Blueprint
from etsy_listings.core.clients.printify.resolve import normalise
from etsy_listings.core.config.pricing_plan import PricingPlan

# ----------------------------------------------------------------------
# The garment picker's rows.
#
# Printify offers hundreds of blueprints and `--category tshirt` still leaves
# dozens, so the rows are columned -- marker, brand, model, title -- and the
# ones this workspace already has a garment profile for sort to the top.
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


def build_blueprint_choices(
    blueprints: list[Blueprint],
    local_keys: set[tuple[str, str]],
    *,
    marker: str = LOCAL_MARKER,
) -> list[Choice[Blueprint]]:
    """Blueprints as aligned ``marker brand model title`` rows.

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
    """Designs as ``date name`` rows, newest first.

    The date is in the row rather than implied by the order because "newest
    first" is invisible otherwise -- and fzf reorders the rows the moment a
    query is typed, at which point the only thing still saying how fresh a
    design is, is the row itself. Ties (a batch exported in one go all carry
    the same second) break on name, so the order is stable rather than
    filesystem-dependent.

    A design that already has a listing is marked: ``new`` refuses to
    overwrite one (``write_listing``), so the row would otherwise look
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


# ----------------------------------------------------------------------
# The pricing-plan picker's rows, and the sentinel row that creates a plan.
# ----------------------------------------------------------------------

CREATE_NEW_PLAN_LABEL = "+ create a new pricing plan"


def build_pricing_plan_choices(
    plans: list[tuple[Path, PricingPlan]],
    garment_profile_slug: str,
    *,
    marker: str = LOCAL_MARKER,
) -> list[Choice[Path]]:
    """Rows for the picker, in :func:`pricing_plan_options`' order -- plans
    declaring this exact garment profile first -- with those carrying the
    marker. Which plans suit a garment is core's answer, shared with the
    listings editor's picker; only the rendering is the wizard's."""
    return [
        Choice(
            value=option.path,
            marked=option.compatible,
            label=f"{marker if option.compatible else ' ' * MARKER_WIDTH}  {option.path.stem}",
        )
        for option in pricing_plan_options(plans, garment_profile_slug)
    ]
