"""Renders a :class:`Plan` as terminal text.

This is presentation, so it lives in ``cli/`` rather than ``engine/``: the
engine produces ``Plan`` / ``StagePlan`` / ``Change`` values and this module
only formats them. The UI's future JSON serialiser is the sibling of this file,
not of the engine -- both consume the same objects and neither may compare
state itself, which is what keeps the two entry points enforcing identical
rules (A2, PRD 20).
"""

from __future__ import annotations

from etsy_listings.engine.change import Plan


def format_plan(plan: Plan) -> str:
    """The PRD's ``plan`` output. Intentionally simple while only the render
    stage exists -- richer per-change rendering (price deltas, before/after
    text) arrives with the stages that emit those change types."""
    lines = [_header(plan), ""]

    runs = [sp for sp in plan.stage_plans if sp.will_run]
    changes = [(sp, change) for sp in plan.stage_plans for change in sp.changes]
    drifts = [(sp, drift) for sp in plan.stage_plans for drift in sp.drift]

    for stage_plan in runs:
        reason = f" ({stage_plan.reason})" if stage_plan.reason else ""
        lines.append(f"  + {stage_plan.stage}{reason}")
    for stage_plan, change in changes:
        lines.append(f"  ~ {stage_plan.stage}: {change}")
    for stage_plan, drift in drifts:
        lines.append(f"  ! drift  {stage_plan.stage}.{drift.path} was edited outside this tool")

    if not plan.stage_plans:
        lines.append("  (no stages configured)")
    elif not (runs or changes or drifts):
        lines.append("  No changes.")

    lines.append("")
    lines.append(f"  {len(runs)} to run, {len(changes)} to change, {len(drifts)} drift warning(s)")
    return "\n".join(lines)


def _header(plan: Plan) -> str:
    if plan.is_live and plan.etsy_listing_id is not None:
        # PRD 21: a live listing is called out, because applying over it edits
        # something buyers can already see.
        return f"{plan.listing}  [LIVE — etsy listing {plan.etsy_listing_id}]"
    return plan.listing
