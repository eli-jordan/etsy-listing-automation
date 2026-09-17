"""The product stage's three-way comparison, as a function of three values.

A2 says each stage writes its own ``plan()``; this is the product stage's,
lifted out of it. Nothing here touches a workspace, a client, a lockfile or a
clock -- :func:`compare` takes the desired document, the applied one and the
live product, and answers what a run would do about them.

It was already pure, and it was already about a hundred and twenty lines. What
it was not was *reachable*: every function carried a leading underscore inside
the stage module, so the only route to a price diff was a fixture workspace,
two fake clients and a `build_plan` call. That is a behaviour test's setup
being paid to ask a unit question, and it is why the price maths went
unasserted -- ``PriceChange`` was checked for its *type* and never for its
before, its after, or its currency.

**One entry point, not four.** ``changes``, ``drift``, ``reason`` and
``actions`` were computed by four separate calls whose results had to agree,
and two of them did not: ``_reason`` restated ``will_run``'s predicate in a
second form, so a rule that existed once could be edited in one place and not
the other. :class:`ProductComparison` computes the rule once and reports every
view of it, which is what makes "will it run?" and "why?" incapable of
disagreeing.
"""

from __future__ import annotations

from dataclasses import dataclass

from etsy_listings.clients.printify.models import Product
from etsy_listings.engine.change import (
    Action,
    Change,
    Drift,
    FieldChange,
    PriceChange,
    drift,
    scalar,
    sequence,
)
from etsy_listings.engine.stages.product_document import (
    AppliedProduct,
    PrintifyProductDesired,
    money,
)

__all__ = ["ProductComparison", "compare"]


@dataclass(frozen=True)
class ProductComparison:
    """What a run would do about this product, and why.

    The fields map one-to-one onto the :class:`~etsy_listings.engine.change.StagePlan`
    the stage returns, so the stage assembles rather than decides.
    """

    will_run: bool
    reason: str | None
    changes: tuple[Change, ...]
    drift: tuple[Drift, ...]
    actions: tuple[Action, ...]


def compare(
    desired: PrintifyProductDesired,
    was: AppliedProduct | None,
    live: Product | None,
) -> ProductComparison:
    """Three-way compare desired, applied and live.

    ``will_run`` is derived from ``reason`` rather than computed beside it:
    the two used to be separate expressions of one rule -- ``was is None or
    bool(changes) or live is None`` on one side, a three-branch string on the
    other -- and separate expressions of one rule are how a stage comes to
    report "no changes" while running anyway.
    """
    wanted = desired.applied()
    changes = _changes(desired, wanted, was)
    reason = _reason(was, live, changes)
    return ProductComparison(
        will_run=reason is not None,
        reason=reason,
        changes=changes,
        drift=_drift(wanted, live),
        actions=_actions(desired, creating=was is None or live is None),
    )


def _reason(
    was: AppliedProduct | None, live: Product | None, changes: tuple[Change, ...]
) -> str | None:
    """Why this stage will run, or ``None`` when it will not.

    The single expression of the rule. ``None`` here *is* ``will_run=False``,
    so there is no third state in which a stage runs for no stated reason.
    """
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
            # Rendered back into `Money` rather than shown as the minor units
            # the document stores. "34900 -> 39900" is the wire format; the
            # user wrote "349 NOK", and that is what a diff has to say back.
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
    """A named colour added or removed (A30).

    Read straight off each variant's own ``colour_slug`` -- carried on
    :class:`~etsy_listings.engine.stages.product_document.AppliedVariant`
    itself rather than looked up from this run's catalog resolution, which is
    what lets a colour Printify has since discontinued (PRD 46) still be
    named in ``removed``: it has no cell left to resolve, but it still has the
    name it was applied under.

    Replaces a UI that would otherwise have to diff two colour lists itself
    to ring a newly added one (A2, decision 4) -- the ``FieldChange`` below
    only ever carried a count.
    """
    wanted_colours = sorted({v.colour_slug for v in wanted.variants})
    was_colours = sorted({v.colour_slug for v in was.variants})
    return sequence("colors", wanted_colours, was_colours)


def _print_area_changes(wanted: AppliedProduct, was: AppliedProduct) -> list[Change]:
    """Print areas matched by ``artwork``, never by position.

    Positional matching read ``was.print_areas[index]``, and the list's order
    came from the order the listing wrote its colours in -- so moving a colour
    to the top of ``colors:`` reported every print area as changed and
    re-uploaded artwork nothing about which had moved. ``artwork`` is the key
    the groups were partitioned on, so it identifies an area across any
    ordering, including the orderings already written into lockfiles by
    versions that did not sort them.
    """
    previous = {area.artwork: area for area in was.print_areas}
    changes: list[Change] = []
    for area in wanted.print_areas:
        before = previous.get(area.artwork)
        if before != area:
            changes.append(
                FieldChange(
                    path=f"print_areas.{area.artwork}",
                    before=before.design_hash if before else None,
                    after=area.design_hash,
                )
            )
    for artwork in sorted(set(previous) - {area.artwork for area in wanted.print_areas}):
        # An artwork key that no longer prints on anything. Positional
        # matching could not see this at all: a shorter list simply stopped
        # being compared.
        changes.append(
            FieldChange(
                path=f"print_areas.{artwork}",
                before=previous[artwork].design_hash,
                after=None,
            )
        )
    return changes


def _drift(wanted: AppliedProduct, live: Product | None) -> tuple[Drift, ...]:
    """What changed in Printify since we last applied.

    Compared against *desired* rather than *applied* only where the two agree
    in shape. The variant matrix is the enabled subset, never the raw list --
    comparing 238 against 6 is a diff that never clears.
    """
    if live is None:
        return ()

    found: list[Drift] = []
    for path, ours, theirs in (
        ("title", wanted.title, live.title),
        ("description", wanted.description, live.description),
    ):
        change = drift(path, ours, theirs)
        if change is not None:
            found.append(change)

    ours_prices = wanted.prices
    if live.enabled_variants() != ours_prices:
        found.append(
            Drift(
                path="variants",
                last_applied=f"{len(ours_prices)} enabled",
                live=f"{len(live.enabled_variants())} enabled",
            )
        )

    if live.visible:
        # The tripwire. Whether a publish lands as a draft is decided outside
        # this tool, so a managed product turning visible is the only signal
        # that something changed the setting that decides it.
        found.append(Drift(path="visible", last_applied=False, live=True))
    return tuple(found)


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
        # PRD 46: reported, never fatal. A cell Printify has discontinued is
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
