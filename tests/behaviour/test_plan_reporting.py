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

from typer.testing import CliRunner

from etsy_listings.cli.app import app

from tests.support.builders import copy_listing, set_copy, set_shop_id

runner = CliRunner()
SHOP_ID = 28819281


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
    """The fixture's copy is still `<generate>`, which PRD 44 refuses. The
    user needs the sentence, not a stack."""
    root = set_shop_id(workspace_root, SHOP_ID)

    result = _plan(root, "take-a-hike")

    assert "Traceback" not in result.output
    assert "<generate>" in result.output


def test_a_gate_refusal_reads_as_a_blocked_stage(workspace_root: Path) -> None:
    """One vocabulary, not two. A refusal and an unconfigured shop are both
    reasons a stage cannot run, so `plan` renders them identically -- and
    counts them in the same place. Four block here: printify_product and
    publish on the `<generate>` copy gate, etsy_listing and etsy_media on
    the Etsy shop id this test never configures."""
    root = set_shop_id(workspace_root, SHOP_ID)

    result = _plan(root, "take-a-hike")

    assert result.exit_code == 0, result.output
    assert "4 blocked" in result.output
    warning = next(line for line in result.output.splitlines() if "<generate>" in line)
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
