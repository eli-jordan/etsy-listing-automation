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

LOCAL_MARKER = "⭐"
LOCAL_MARKER_FALLBACK = "* "
"""Two terminal columns either way -- ``⭐`` is East Asian Wide, so it occupies
the same width as the two-character ASCII fallback and the marker column stays
aligned on a terminal that cannot print it."""

MARKER_WIDTH = 2


@dataclass(frozen=True)
class Choice[T]:
    """One row of a picker: the thing itself, and the text offered for it."""

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
    entries = [(item, marked(item)) for item in items]
    entries.sort(key=lambda entry: (not entry[1], sort_key(entry[0])))
    return [
        Choice(
            value=item,
            marked=is_marked,
            label=_marked_label(marker, label(item), is_marked=is_marked),
        )
        for item, is_marked in entries
    ]


def _marked_label(marker: str, text: str, *, is_marked: bool) -> str:
    return f"{marker if is_marked else ' ' * MARKER_WIDTH}  {text}"


def build_blueprint_choices(
    blueprints: list[Blueprint],
    local_keys: set[tuple[str, str]],
    *,
    marker: str = LOCAL_MARKER,
) -> list[Choice[Blueprint]]:
    """Blueprints as aligned ``marker brand model title`` rows.

    Brand and model identify a blank ("Gildan 18500"); Printify's titles do
    not ("Unisex Pullover Hoodie" is sold under several brands). Garments
    with a local garment profile come first, marked.
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


def build_design_choices(paths: list[Path], listing_names: set[str]) -> list[Choice[Path]]:
    """Designs as ``date name`` rows, newest first.

    The date is in the label because fzf reorders rows once a query is
    typed. A design that already has a listing gets a trailing note, not
    :func:`marked_choices`, which would sort it to the top.
    """
    entries = sorted(
        ((path, path.stat().st_mtime) for path in paths),
        key=lambda entry: (-entry[1], entry[0].stem.lower()),
    )
    local_tz = datetime.now().astimezone().tzinfo
    return [
        Choice(
            value=path,
            marked=path.stem in listing_names,
            label=(
                f"{datetime.fromtimestamp(modified, tz=local_tz):%Y-%m-%d %H:%M}  {path.stem}"
                f"{'  (listing exists)' if path.stem in listing_names else ''}"
            ),
        )
        for path, modified in entries
    ]


CREATE_NEW_PLAN_LABEL = "+ create a new pricing plan"


def build_pricing_plan_choices(
    plans: list[tuple[Path, PricingPlan]],
    garment_profile_slug: str,
    *,
    marker: str = LOCAL_MARKER,
) -> list[Choice[Path]]:
    """Rows in :func:`pricing_plan_options`' order, the plans for this exact
    garment profile first and marked."""
    return [
        Choice(
            value=option.path,
            marked=option.compatible,
            label=_marked_label(marker, option.path.stem, is_marked=option.compatible),
        )
        for option in pricing_plan_options(plans, garment_profile_slug)
    ]
