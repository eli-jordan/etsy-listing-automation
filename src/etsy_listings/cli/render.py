"""Renders a :class:`Plan` as terminal text.

This is presentation, so it lives in ``cli/`` rather than ``engine/``: the
engine produces ``Plan`` / ``StagePlan`` / ``Change`` / ``Action`` values and
this module only formats them. The UI's future JSON serialiser is the sibling
of this file, not of the engine -- both consume the same objects and neither
may compare state itself, which is what keeps the two entry points enforcing
identical rules (A2, PRD 20). In particular nothing here may stat a file: an
output is shown as missing because the stage observed it missing.
"""

from __future__ import annotations

from etsy_listings.engine.change import Plan, StagePlan


def format_plan(plan: Plan) -> str:
    """The PRD's ``plan`` output: which stages run, why, and -- for each one --
    the concrete actions it will take, with the files each reads and writes.
    Richer per-change rendering (price deltas, before/after text) arrives with
    the stages that emit those change types."""
    lines = [_header(plan), ""]

    runs = [sp for sp in plan.stage_plans if sp.will_run]
    blocked = [sp for sp in plan.stage_plans if sp.blocked]
    changes = [(sp, change) for sp in plan.stage_plans for change in sp.changes]
    drifts = [(sp, drift) for sp in plan.stage_plans for drift in sp.drift]
    action_count = sum(len(sp.actions) for sp in plan.stage_plans)

    for stage_plan in runs:
        reason = f" ({stage_plan.reason})" if stage_plan.reason else ""
        lines.append(f"  + {stage_plan.stage}{reason}")
        lines.extend(_format_actions(stage_plan))
    for stage_plan, change in changes:
        lines.append(f"  ~ {stage_plan.stage}: {change}")
    for stage_plan, drift in drifts:
        lines.append(f"  ! drift  {stage_plan.stage}.{drift.path} was edited outside this tool")
    # After the work and before the summary: a blocked stage is context for
    # what is missing from the run, not part of it.
    for stage_plan in blocked:
        lines.append(f"  - {stage_plan.stage}: {stage_plan.blocked}")

    if not plan.stage_plans:
        lines.append("  (no stages configured)")
    elif not (runs or changes or drifts):
        # Still "No changes." even when something is blocked: the blocked
        # line sits directly below and carries the qualification, so the two
        # together say what is true. It was the *absence* of that line that
        # made this a lie.
        lines.insert(len(lines) - len(blocked), "  No changes.")

    lines.append("")
    lines.append(
        f"  {len(runs)} to run{_actions_suffix(action_count)}, "
        f"{len(changes)} to change, {len(drifts)} drift warning(s)"
    )
    return "\n".join(lines)


def _actions_suffix(count: int) -> str:
    if count == 0:
        return ""
    return f" ({count} action{'' if count == 1 else 's'})"


def _format_actions(stage_plan: StagePlan) -> list[str]:
    """One block per action: what it does, what it reads, what it writes.

    ``plan`` answering only "the render stage will run" left the obvious next
    question -- over which scenes, from which files, onto which files -- to be
    answered by reading the config by hand.
    """
    lines: list[str] = []
    for action in stage_plan.actions:
        lines.append(f"      {action.description}")
        for index, path in enumerate(action.inputs):
            label = "in  " if index == 0 else "    "
            lines.append(f"        {label} {path}")
        for path in action.outputs:
            marker = "   (missing)" if path in action.missing_outputs else ""
            lines.append(f"        out  {path}{marker}")
    return lines


def _header(plan: Plan) -> str:
    if plan.is_live and plan.etsy_listing_id is not None:
        # PRD 21: a live listing is called out, because applying over it edits
        # something buyers can already see.
        return f"{plan.listing}  [LIVE — etsy listing {plan.etsy_listing_id}]"
    return plan.listing
