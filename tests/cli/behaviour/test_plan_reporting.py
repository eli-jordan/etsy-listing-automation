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

These are the command's own output witnesses, through the real pipeline:
one blocked stage, one gate refusal, a batch, and `apply`. Which stages
block is ``tests/core/behaviour/test_run.py``'s; how a blocked stage, its
remedy and the summary are laid out is ``tests/cli/unit/test_format_plan.py``'s
over typed plans (test-suite quality plan, PR 9).
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
    lines = result.output.splitlines()
    warning = lines.index(
        "  ! this listing will not be uploaded to Printify: no Printify shop is "
        "configured for this workspace."
    )
    assert lines[warning + 2] == "      (printify_product will not run)"
    assert "+ render" in result.output
    assert "0 to change, 4 blocked, 0 drift warning(s)" in result.output


# ------------------------------------------------------------ gate refusals


def test_a_gate_refusal_is_an_actionable_message_not_a_traceback(
    workspace_root: Path,
) -> None:
    """The fixture's copy is still blank, which ADR-0022 refuses. The user
    needs the sentence, not a stack."""
    root = set_shop_id(workspace_root, SHOP_ID)

    result = _plan(root, "take-a-hike")

    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
    assert "  ! etsy.title is empty" in result.output


def test_a_gate_refusal_does_not_halt_a_batch(workspace_root: Path) -> None:
    """continue-on-error: continue-on-error. One listing that cannot be planned must not
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
    """One vocabulary, both routes. The stage supplies the sentence;
    neither the plan renderer nor `apply` writes its own version of it."""
    blocked_line = "will not be uploaded to Printify"
    planned = next(
        ln for ln in _plan(workspace_root, "take-a-hike").output.splitlines() if blocked_line in ln
    )
    applied = next(
        ln for ln in _apply(workspace_root, "take-a-hike").output.splitlines() if blocked_line in ln
    )

    assert planned == applied
