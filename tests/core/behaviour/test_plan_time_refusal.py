"""A stage that finds it cannot run only once it has read live state.

`publish`'s below-cost check needs ``variants[].cost``, so it cannot refuse
from ``desired()`` (ADR-0020's amendment) and returns ``Verdict.refused``
from ``plan()`` instead. The engine has to turn that into the same blocked
stage a ``desired()`` refusal is, and never execute it. Moved from the
`plan` command's output tests (test-suite quality plan, PR 9); how a blocked
stage reads is ``tests/cli/unit/test_format_plan.py``'s.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from etsy_listings.core.engine.apply import execute
from etsy_listings.core.engine.change import Verdict
from etsy_listings.core.engine.plan import build_plan

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import a_context, a_lock

REFUSAL = "this listing will not be published: the price is below cost.\nRaise it."


class _Empty(BaseModel):
    """A stage's applied document, for a stage that has nothing to remember."""


class _RefusingStage:
    """A stage that gets as far as comparing and *then* finds it cannot run.

    Stands in for `publish`'s below-cost check, which needs ``variants[].cost``
    and so cannot refuse from ``desired()`` (ADR-0020's amendment). Written as a
    stub rather than driven through `publish` because the subject here is what
    the user is shown, not what Printify charges: reaching the real check needs
    a published product and a live cost, and neither would make the assertion
    below any truer.
    """

    name = "refuser"
    local = True
    group: str | None = None
    applied_model = _Empty

    def desired(self, ctx, listing, applied):  # noqa: ANN001, ANN201, ARG002
        return "wanted"

    def read_live(self, ctx, listing, lock, applied):  # noqa: ANN001, ANN201, ARG002
        return "live"

    def plan(self, desired, applied, live):  # noqa: ANN001, ANN201, ARG002
        return Verdict.refused(REFUSAL)

    def apply(self, ctx, desired, applied, live, lock):  # noqa: ANN001, ANN201, ARG002
        raise AssertionError("a refused stage must never be executed")


def test_a_refused_stage_is_not_executed(workspace_root: Path) -> None:
    """`_RefusingStage.apply` raises if it is ever reached. A refusal has to
    stop the work as well as report it -- the same guarantee a `desired()`
    refusal already gave."""
    ctx = a_context(workspace_root)
    planned = build_plan(ctx, LISTING, a_lock(), [_RefusingStage()])

    execute(ctx, planned, a_lock())


def test_a_refusal_from_plan_is_a_blocked_stage_like_one_from_desired(
    workspace_root: Path,
) -> None:
    """The half of the vocabulary that shipped invisible: a refusal returned
    as a won't-run verdict carrying a reason reached nobody, because only
    stages that *will* run print a reason. It must arrive as ``blocked``,
    whole -- the remedy line included."""
    ctx = a_context(workspace_root)
    planned = build_plan(ctx, LISTING, a_lock(), [_RefusingStage()])

    (stage_plan,) = planned.plan.stage_plans
    assert stage_plan.blocked == REFUSAL
    assert not stage_plan.will_run
