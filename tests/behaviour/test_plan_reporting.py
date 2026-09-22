"""What `plan` tells the user when a stage cannot run.

Both cases here were found by running the tool rather than by testing it, and
both had the same shape: the engine knew exactly what was wrong and the
terminal said nothing useful.

- A stage that opts out (no Printify shop configured) rendered as *silence*,
  so a workspace with a whole unrun stage reported "No changes."
- A gate refusal escaped `plan` as a traceback, which is both unreadable and,
  worse, fatal to the *rest of the plan*: the exception unwound the stage
  walk, so an undersized design cost the user the render stage's report too.

Both are now the same thing -- a blocked stage -- and `plan` reports either
the same way, in full, without exiting non-zero. `plan` is a report; a
workspace that is not ready for a stage yet is not an error, it is the thing
the report is for.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel
from typer.testing import CliRunner

from etsy_listings.cli.app import app
from etsy_listings.cli.render import format_plan
from etsy_listings.engine.apply import execute
from etsy_listings.engine.change import Drift, Plan, StagePlan, Verdict
from etsy_listings.engine.plan import build_plan

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import a_context, a_lock, copy_listing, set_copy, set_shop_id

runner = CliRunner()
SHOP_ID = 28819281


class _Empty(BaseModel):
    """A stage's applied document, for a stage that has nothing to remember."""


def _plan(root: Path, *args: str):
    return runner.invoke(app, ["plan", *args, "--root", str(root)])


def _apply(root: Path, *args: str):
    return runner.invoke(app, ["apply", *args, "--root", str(root)])


# ------------------------------------------------------- the unconfigured stage


def test_a_stage_that_cannot_run_is_named_rather_than_hidden(workspace_root: Path) -> None:
    """The fixture workspace has no `printify.shop_id`, so the product stage
    opts out. Reporting "No changes." there is a lie by omission: there is a
    stage that would do something and cannot."""
    result = _plan(workspace_root, "take-a-hike")

    assert result.exit_code == 0, result.output
    assert "printify_product" in result.output


def test_it_warns_in_the_users_terms_not_the_pipelines(workspace_root: Path) -> None:
    """ "printify_product will not run" describes the machinery. What the user
    loses is the listing not reaching Printify, and that is the sentence that
    has to be on screen."""
    result = _plan(workspace_root, "take-a-hike")

    assert "will not be uploaded to Printify" in result.output


def test_the_warning_is_marked_as_one(workspace_root: Path) -> None:
    """It sat below "No changes." as a dim dash line, which reads as a note.
    A listing silently not reaching Printify is not a note."""
    warning_line = next(
        line for line in result_lines(workspace_root) if "will not be uploaded" in line
    )

    assert warning_line.lstrip().startswith("!")


def test_the_warning_leads(workspace_root: Path) -> None:
    """What a run will *not* do is the more surprising half. Reporting the
    work first and qualifying it afterwards is how this was missed in the
    first place."""
    lines = result_lines(workspace_root)
    warning = next(i for i, line in enumerate(lines) if "will not be uploaded" in line)
    first_work = next(i for i, line in enumerate(lines) if line.lstrip().startswith("+"))

    assert warning < first_work


def test_it_says_what_to_do_about_it(workspace_root: Path) -> None:
    result = _plan(workspace_root, "take-a-hike")

    assert "setup" in result.output


def test_the_summary_counts_the_blocked_stage(workspace_root: Path) -> None:
    """A summary that says "0 to run, 0 to change" and nothing else is the
    same omission one line further down. Four stages block on an
    unconfigured workspace: printify_product, publish, etsy_listing and
    etsy_media all need a shop id this fixture does not have."""
    result = _plan(workspace_root, "take-a-hike")

    assert "4 blocked" in result.output


def test_a_blocked_stage_is_not_counted_as_work_to_do(workspace_root: Path) -> None:
    """It is not "to run" -- nothing will happen to it. Counting it would make
    the summary disagree with the body."""
    result = _plan(workspace_root, "take-a-hike")

    assert "1 to run" in result.output, "the render stage, and only it"


def result_lines(root: Path) -> list[str]:
    return _plan(root, "take-a-hike").output.splitlines()


def test_a_configured_workspace_does_not_report_a_block(workspace_root: Path) -> None:
    root = set_shop_id(workspace_root, SHOP_ID)
    set_copy(root, title="Take A Hike Tee", description="A retro sunset.")

    result = _plan(root, "take-a-hike")

    assert "run `etsy-listings setup`" not in result.output


# ------------------------------------------------------------ gate refusals


def test_a_gate_refusal_is_an_actionable_message_not_a_traceback(
    workspace_root: Path,
) -> None:
    """The fixture's copy is still blank, which PRD 44 refuses. The user
    needs the sentence, not a stack."""
    root = set_shop_id(workspace_root, SHOP_ID)

    result = _plan(root, "take-a-hike")

    assert "Traceback" not in result.output
    assert "etsy.title is empty" in result.output


def test_a_gate_refusal_reads_as_a_blocked_stage(workspace_root: Path) -> None:
    """One vocabulary, not two. A refusal and an unconfigured shop are both
    reasons a stage cannot run, so `plan` renders them identically -- and
    counts them in the same place. Four block here: printify_product and
    publish on the empty-copy gate, etsy_listing and etsy_media on the Etsy
    shop id this test never configures."""
    root = set_shop_id(workspace_root, SHOP_ID)

    result = _plan(root, "take-a-hike")

    assert result.exit_code == 0, result.output
    assert "4 blocked" in result.output
    warning = next(line for line in result.output.splitlines() if "etsy.title is empty" in line)
    assert warning.lstrip().startswith("!")


def test_a_gate_refusal_leaves_the_rest_of_the_plan_standing(workspace_root: Path) -> None:
    """The bug that made the refusal a returned value. It was raised, so it
    unwound the stage walk: a listing whose copy was not written yet reported
    one line of error and nothing at all about the mockups it would render."""
    root = set_shop_id(workspace_root, SHOP_ID)

    result = _plan(root, "take-a-hike")

    assert "+ render" in result.output
    assert "1 to run" in result.output


def test_a_gate_refusal_does_not_halt_a_batch(workspace_root: Path) -> None:
    """PRD 16: continue-on-error. One listing that cannot be planned must not
    stop the rest -- which is the whole reason `--all` is safe to run."""
    root = set_shop_id(workspace_root, SHOP_ID)
    copy_listing(root, "second-listing")
    set_copy(root, title="A Real Title", description="Real copy.", listing="second-listing")

    result = _plan(root, "--all")

    assert "take-a-hike" in result.output
    assert "second-listing" in result.output, "the batch carried on past the refusal"


# ------------------------------------------------------------ what apply says


def test_apply_says_what_it_will_not_do(workspace_root: Path) -> None:
    """`apply` prints no plan, so a blocked stage would otherwise be invisible
    on the route where it matters most: the user asked for the work to happen
    and part of it silently did not."""
    result = _apply(workspace_root, "take-a-hike")

    assert "will not be uploaded to Printify" in result.output
    assert "setup" in result.output


def test_apply_still_does_the_work_it_can(workspace_root: Path) -> None:
    """A blocked stage is not a failed run. The render stage has nothing to do
    with Printify, and a workspace that has not opted into Phase 2 is not
    broken -- so the mockups are rendered and the exit code stays clean."""
    result = _apply(workspace_root, "take-a-hike")

    assert result.exit_code == 0, result.output
    renders = workspace_root / ".cache" / "renders" / "take-a-hike" / "flat-lay-01"
    assert (renders / "black.png").is_file()


def test_apply_says_it_in_the_same_words_plan_does(workspace_root: Path) -> None:
    """One vocabulary, both routes (PRD 20). The stage supplies the sentence;
    neither the plan renderer nor `apply` writes its own version of it."""
    blocked_line = "will not be uploaded to Printify"
    planned = next(
        ln for ln in _plan(workspace_root, "take-a-hike").output.splitlines() if blocked_line in ln
    )
    applied = next(
        ln for ln in _apply(workspace_root, "take-a-hike").output.splitlines() if blocked_line in ln
    )

    assert planned == applied


# ------------------------------------------- the refusal only `live` can prove


class _RefusingStage:
    """A stage that gets as far as comparing and *then* finds it cannot run.

    Stands in for `publish`'s below-cost check, which needs ``variants[].cost``
    and so cannot refuse from ``desired()`` (PRD 40's amendment). Written as a
    stub rather than driven through `publish` because the subject here is what
    the user is shown, not what Printify charges: reaching the real check needs
    a published product and a live cost, and neither would make the assertion
    below any truer.
    """

    name = "refuser"
    local = True
    applied_model = _Empty

    def desired(self, ctx, listing, applied):  # noqa: ANN001, ANN201, ARG002
        return "wanted"

    def read_live(self, ctx, listing, lock, applied):  # noqa: ANN001, ANN201, ARG002
        return "live"

    def plan(self, desired, applied, live):  # noqa: ANN001, ANN201, ARG002
        return Verdict.refused(
            "this listing will not be published: the price is below cost.\nRaise it."
        )

    def apply(self, ctx, desired, applied, live, lock):  # noqa: ANN001, ANN201, ARG002
        raise AssertionError("a refused stage must never be executed")


def test_a_refusal_from_plan_reads_like_one_from_desired(workspace_root: Path) -> None:
    """The half of the vocabulary that shipped invisible. `format_plan` prints
    a `reason` only for stages that *will* run, so a refusal returned as a
    won't-run verdict carrying a reason reached nobody -- the listing was
    skipped under a plan reading "No changes."."""
    ctx = a_context(workspace_root)
    planned = build_plan(ctx, LISTING, a_lock(), [_RefusingStage()])

    output = format_plan(planned.plan)

    assert "below cost" in output
    assert "Raise it." in output
    assert "(refuser will not run)" in output
    # Counted as a refusal in the summary, not left to be inferred from a
    # stage that quietly did nothing.
    assert "1 blocked" in output


# ------------------------------------------------------------ drift labels


def test_a_drift_with_labels_shows_names_not_ids(workspace_root: Path) -> None:
    """A30: a stage that could resolve a name for a drifted id shows it,
    rather than only the id `format_plan` printed before this PR."""
    plan = Plan(
        listing="take-a-hike",
        is_live=False,
        etsy_listing_id=None,
        stage_plans=(
            StagePlan.no_work(
                "etsy_listing",
                drift=(
                    Drift(
                        path="shipping_profile_id",
                        last_applied=1,
                        live=999,
                        last_applied_label="NOK standard tee",
                        live_label="US origin",
                    ),
                ),
            ),
        ),
    )

    output = format_plan(plan)

    assert "was NOK standard tee, Etsy now says US origin" in output
    assert "999" not in output, "the raw id has a name now, so it need not appear"


def test_a_drift_with_no_label_still_shows_the_raw_values(workspace_root: Path) -> None:
    """Every drift before this PR, and every one whose sides are plain text
    already -- a title, a description -- has no label at all, and `plan`
    must go on printing exactly what it printed before."""
    plan = Plan(
        listing="take-a-hike",
        is_live=False,
        etsy_listing_id=None,
        stage_plans=(
            StagePlan.no_work(
                "etsy_listing",
                drift=(Drift(path="title", last_applied="Old Title", live="New Title"),),
            ),
        ),
    )

    output = format_plan(plan)

    assert "etsy_listing.title was edited outside this tool" in output
    assert "(was" not in output


def test_a_refused_stage_is_not_executed(workspace_root: Path) -> None:
    """`_RefusingStage.apply` raises if it is ever reached. A refusal has to
    stop the work as well as report it -- the same guarantee a `desired()`
    refusal already gave."""
    ctx = a_context(workspace_root)
    planned = build_plan(ctx, LISTING, a_lock(), [_RefusingStage()])

    execute(ctx, planned, a_lock())
