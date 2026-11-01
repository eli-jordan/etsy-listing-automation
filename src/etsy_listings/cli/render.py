"""Renders a :class:`Plan` as terminal text.

This is presentation, so it lives in ``cli/`` rather than ``engine/``: the
engine produces ``Plan`` / ``StagePlan`` / ``Change`` / ``Action`` values and
this module only formats them. The UI's JSON serialiser is the sibling
of this file, not of the engine -- both consume the same objects and neither
may compare state itself, which is what keeps the two entry points enforcing
identical rules. In particular nothing here may stat a file: an
output is shown as missing because the stage observed it missing.
"""

from __future__ import annotations

from dataclasses import dataclass

from etsy_listings.core.engine.change import Action, Change, Drift, Plan, StagePlan


def format_plan(plan: Plan) -> str:
    """The ``plan`` output: which stages run, why, and -- for each one --
    the concrete actions it will take, with the files each reads and writes.
    Richer per-change rendering (price deltas, before/after text) arrives with
    the stages that emit those change types."""
    sections = _Sections.of(plan)
    lines = [_header(plan), "", *_body(plan, sections), ""]
    lines.append(
        f"  {len(sections.runs)} to run{_actions_suffix(sections.action_count)}, "
        f"{len(sections.changes)} to change{_blocked_suffix(len(sections.blocked))}, "
        f"{len(sections.drifts)} drift warning(s)"
    )
    return "\n".join(lines)


@dataclass(frozen=True)
class _Sections:
    """A plan's stages grouped the way ``plan`` prints them."""

    runs: list[StagePlan]
    blocked: list[StagePlan]
    changes: list[tuple[StagePlan, Change]]
    drifts: list[tuple[StagePlan, Drift]]
    action_count: int

    @classmethod
    def of(cls, plan: Plan) -> _Sections:
        return cls(
            runs=[sp for sp in plan.stage_plans if sp.will_run],
            blocked=[sp for sp in plan.stage_plans if sp.blocked],
            changes=[(sp, change) for sp in plan.stage_plans for change in sp.changes],
            drifts=[(sp, drift) for sp in plan.stage_plans for drift in sp.drift],
            action_count=sum(len(sp.actions) for sp in plan.stage_plans),
        )


def _body(plan: Plan, sections: _Sections) -> list[str]:
    # Blocked stages lead. What a run will *not* do is the more surprising
    # half, and burying it under "No changes." is exactly how a listing goes
    # un-uploaded without anyone noticing.
    lines = [line for stage_plan in sections.blocked for line in format_blocked(stage_plan)]
    lines.extend(line for stage_plan in sections.runs for line in _run_lines(stage_plan))
    lines.extend(f"  ~ {_name(stage_plan)}: {change}" for stage_plan, change in sections.changes)
    lines.extend(_drift_line(stage_plan, drift) for stage_plan, drift in sections.drifts)

    if not plan.stage_plans:
        lines.append("  (no stages configured)")
    elif not (sections.runs or sections.changes or sections.drifts):
        lines.append("  No changes.")
    return lines


def _run_lines(stage_plan: StagePlan) -> list[str]:
    reason = f" ({stage_plan.reason})" if stage_plan.reason else ""
    return [f"  + {_name(stage_plan)}{reason}", *_format_actions(stage_plan)]


def _drift_line(stage_plan: StagePlan, drift: Drift) -> str:
    return (
        f"  ! drift  {_name(stage_plan)}.{drift.path} was edited outside this "
        f"tool{_drift_detail(drift)}"
    )


def format_blocked(stage_plan: StagePlan) -> list[str]:
    """A stage that cannot run, as a warning rather than a footnote.

    The first line is the consequence in the user's terms -- what will not
    happen to their listing -- and any further lines are the remedy, indented
    under it. The stage supplies both, because *why* a stage is blocked is
    engine knowledge; only the shape of it belongs here.

    Public because ``apply`` shows these too. A blocked stage is the one thing
    ``apply`` must not stay quiet about: it is doing less than it was asked
    to, and the whole point of the ``blocked`` vocabulary is that both routes
    say so in the same words.
    """
    message = (stage_plan.blocked or "").splitlines()
    head, *rest = message or [""]
    lines = [f"  ! {head}"]
    lines.extend(f"      {line}" for line in rest)
    lines.append(f"      ({_name(stage_plan)} will not run)")
    return lines


def _name(stage_plan: StagePlan) -> str:
    """``etsy_media/etsy_videos``: a stage shown under the one the engine
    groups it with (ADR-0045: one gallery, two stages), else its own name."""
    if stage_plan.group is None:
        return stage_plan.stage
    return f"{stage_plan.group}/{stage_plan.stage}"


def _drift_detail(drift: Drift) -> str:
    """`` (was NOK standard tee, Etsy now says US origin)`` -- a name in
    place of the raw id when the stage that found the drift could resolve
    one, on either side independently: the last-applied side almost
    always can (this stage already stored the name beside the id it
    resolved), the live side only when this run's catalog happened to fetch
    the list a fresh id turned up in. Nothing is printed for a drift with no
    label at all, which is every drift before this PR and every one whose
    two sides are already plain text (a title, a description)."""
    before = drift.last_applied_label
    after = drift.live_label
    if before is None and after is None:
        return ""
    shown_before = before if before is not None else drift.last_applied
    shown_after = after if after is not None else drift.live
    return f" (was {shown_before}, Etsy now says {shown_after})"


def _blocked_suffix(count: int) -> str:
    if count == 0:
        return ""
    return f", {count} blocked"


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
    return [line for action in stage_plan.actions for line in _action_lines(action)]


def _action_lines(action: Action) -> list[str]:
    lines = [f"      {action.description}"]
    for index, path in enumerate(action.inputs):
        label = "in  " if index == 0 else "    "
        lines.append(f"        {label} {path}")
    for path in action.outputs:
        marker = "   (missing)" if path in action.missing_outputs else ""
        lines.append(f"        out  {path}{marker}")
    return lines


def _header(plan: Plan) -> str:
    if plan.is_live and plan.etsy_listing_id is not None:
        # a live listing is called out, because applying over it edits
        # something buyers can already see.
        return f"{plan.listing}  [LIVE — etsy listing {plan.etsy_listing_id}]"
    return plan.listing
