"""The product stage's pure three-way comparison."""

from __future__ import annotations

from dataclasses import dataclass

from etsy_listings.core.clients.printify.models import Product
from etsy_listings.core.engine.change import (
    Action,
    Change,
    Drift,
    FieldChange,
    PriceChange,
    StageIdle,
    StageWork,
    drift,
    scalar,
    sequence,
)
from etsy_listings.core.engine.lock import short_digest
from etsy_listings.core.engine.stages.product_document import (
    AppliedProduct,
    PrintifyProductDesired,
    money,
)

__all__ = ["ProductComparison", "compare"]


@dataclass(frozen=True)
class ProductComparison:
    """What a run would do about this product, and why.

    The fields map one-to-one onto the :class:`~etsy_listings.core.engine.change.StagePlan`
    the stage returns, so the stage assembles rather than decides.
    """

    outcome: StageIdle | StageWork
    drift: tuple[Drift, ...]

    @property
    def will_run(self) -> bool:
        return isinstance(self.outcome, StageWork)

    @property
    def reason(self) -> str | None:
        return self.outcome.reason if isinstance(self.outcome, StageWork) else None

    @property
    def changes(self) -> tuple[Change, ...]:
        return self.outcome.changes if isinstance(self.outcome, StageWork) else ()

    @property
    def actions(self) -> tuple[Action, ...]:
        return self.outcome.actions if isinstance(self.outcome, StageWork) else ()


def compare(
    desired: PrintifyProductDesired,
    was: AppliedProduct | None,
    live: Product | None,
) -> ProductComparison:
    wanted = desired.applied()
    changes = _changes(desired, wanted, was)
    reason = _reason(was, live, changes)
    outcome: StageIdle | StageWork
    if reason is None:
        outcome = StageIdle()
    else:
        outcome = StageWork(
            reason=reason,
            changes=changes,
            actions=_actions(desired, creating=was is None or live is None),
        )
    return ProductComparison(outcome=outcome, drift=_drift(was, live))


def _reason(
    was: AppliedProduct | None, live: Product | None, changes: tuple[Change, ...]
) -> str | None:
    if was is None:
        return "no Printify product yet -- it will be created"
    if live is None:
        return "the Printify product this listing named is gone -- it will be created again"
    if changes:
        return "the product differs from the listing"
    return None


def _changes(
    desired: PrintifyProductDesired, wanted: AppliedProduct, was: AppliedProduct | None
) -> tuple[Change, ...]:
    if was is None:
        return ()

    changes: list[Change] = []
    for path in ("title", "description", "position"):
        change = scalar(path, getattr(wanted, path), getattr(was, path))
        if change is not None:
            changes.append(change)

    colour_change = _colour_change(wanted, was)
    if colour_change is not None:
        changes.append(colour_change)

    was_prices = was.prices
    for variant in sorted(desired.variants, key=lambda v: v.id):
        previous = was_prices.get(variant.id)
        if previous is not None and previous != variant.price:
            changes.append(
                PriceChange(
                    size=variant.size,
                    color=variant.colour_slug,
                    before=money(previous, desired.currency),
                    after=money(variant.price, desired.currency),
                )
            )

    if set(wanted.prices) != set(was_prices):
        changes.append(
            FieldChange(path="variants", before=len(was.variants), after=len(wanted.variants))
        )

    changes.extend(_print_area_changes(wanted, was))
    return tuple(changes)


def _colour_change(wanted: AppliedProduct, was: AppliedProduct) -> Change | None:
    wanted_colours = sorted({v.colour_slug for v in wanted.variants})
    was_colours = sorted({v.colour_slug for v in was.variants})
    return sequence("colors", wanted_colours, was_colours)


def _print_area_changes(wanted: AppliedProduct, was: AppliedProduct) -> list[Change]:
    """Print areas matched by design hash (ADR-0053), never by position."""
    previous = {area.design_hash: area for area in was.print_areas}
    changes: list[Change] = []
    for area in wanted.print_areas:
        before = previous.get(area.design_hash)
        if before != area:
            changes.append(
                FieldChange(
                    path=_area_path(area.design_hash),
                    before=before.design_hash if before else None,
                    after=area.design_hash,
                )
            )
    wanted_hashes = {area.design_hash for area in wanted.print_areas}
    changes.extend(
        FieldChange(path=_area_path(digest), before=digest, after=None)
        for digest in sorted(set(previous) - wanted_hashes)
    )
    return changes


def _area_path(design_hash: str) -> str:
    return f"print_areas.{short_digest(design_hash)}"


def _drift(was: AppliedProduct | None, live: Product | None) -> tuple[Drift, ...]:
    if was is None or live is None:
        return ()

    found: list[Drift] = []
    for path, ours, theirs in (
        ("title", was.title, live.title),
        ("description", was.description, live.description),
    ):
        change = drift(path, ours, theirs)
        if change is not None:
            found.append(change)

    variants = _variants_drift(was.prices, live.enabled_variants())
    if variants is not None:
        found.append(variants)
    return tuple(found)


def _variants_drift(ours: dict[int, int], theirs: dict[int, int]) -> Drift | None:
    if theirs == ours:
        return None
    live_description = f"{len(theirs)} enabled"
    if len(theirs) == len(ours):
        live_description += f" ({' and '.join(_variant_details(ours, theirs))})"
    return Drift(path="variants", last_applied=f"{len(ours)} enabled", live=live_description)


def _variant_details(ours: dict[int, int], theirs: dict[int, int]) -> list[str]:
    selection_changed = set(theirs) != set(ours)
    prices_changed = sum(
        theirs[variant_id] != ours[variant_id] for variant_id in set(theirs) & set(ours)
    )
    details: list[str] = []
    if selection_changed:
        details.append("selection changed")
    if prices_changed:
        noun = "price" if prices_changed == 1 else "prices"
        details.append(f"{prices_changed} {noun} changed")
    return details


def _actions(desired: PrintifyProductDesired, *, creating: bool) -> tuple[Action, ...]:
    verb = "create" if creating else "update"
    described = (
        f"{verb} a Printify product: {len(desired.variants)} variants across "
        f"{len(desired.groups)} print area(s)"
    )
    actions = [
        Action(
            description=described,
            inputs=tuple(sorted(group.design.name for group in desired.groups)),
        )
    ]
    if desired.missing:
        # reported, never fatal. A cell Printify has discontinued is
        # its fact, not the user's mistake -- but a listing quietly selling
        # five sizes where it asked for six is worth saying out loud.
        listed = ", ".join(f"{colour}/{size}" for colour, size in desired.missing)
        actions.append(
            Action(
                description=(
                    f"skip {len(desired.missing)} colour/size "
                    f"combination(s) this garment no longer offers: {listed}"
                )
            )
        )
    return tuple(actions)
