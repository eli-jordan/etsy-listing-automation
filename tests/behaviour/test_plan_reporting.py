"""What `plan` tells the user when a stage cannot run.

Both cases here were found by running the tool rather than by testing it, and
both had the same shape: the engine knew exactly what was wrong and the
terminal said nothing useful.

- A stage that opts out (no Printify shop configured) rendered as *silence*,
  so a workspace with a whole unrun stage reported "No changes."
- A gate refusal escaped `plan` as a traceback, which is both unreadable and
  fatal to a `--all` batch that PRD 16 requires to continue on error.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from etsy_listings.cli.app import app

runner = CliRunner()
SHOP_ID = 28819281


def _with_shop_id(root: Path) -> Path:
    shop = root / "shop.yaml"
    document = yaml.safe_load(shop.read_text(encoding="utf-8"))
    document["printify"] = {"shop_id": SHOP_ID}
    shop.write_text(yaml.safe_dump(document), encoding="utf-8")
    return root


def _plan(root: Path, *args: str):
    return runner.invoke(app, ["plan", *args, "--root", str(root)])


# ------------------------------------------------------- the unconfigured stage


def test_a_stage_that_cannot_run_is_named_rather_than_hidden(workspace_root: Path) -> None:
    """The fixture workspace has no `printify.shop_id`, so the product stage
    opts out. Reporting "No changes." there is a lie by omission: there is a
    stage that would do something and cannot."""
    result = _plan(workspace_root, "take-a-hike")

    assert result.exit_code == 0, result.output
    assert "printify_product" in result.output


def test_it_says_what_to_do_about_it(workspace_root: Path) -> None:
    result = _plan(workspace_root, "take-a-hike")

    assert "setup" in result.output


def test_a_blocked_stage_is_not_counted_as_work_to_do(workspace_root: Path) -> None:
    """It is not "to run" -- nothing will happen to it. Counting it would make
    the summary disagree with the body."""
    result = _plan(workspace_root, "take-a-hike")

    assert "1 to run" in result.output, "the render stage, and only it"


def test_a_configured_workspace_does_not_report_a_block(workspace_root: Path) -> None:
    root = _with_shop_id(workspace_root)
    _write_copy(root)

    result = _plan(root, "take-a-hike")

    assert "run `etsy-listings setup`" not in result.output


def _write_copy(root: Path) -> None:
    path = root / "listings" / "take-a-hike" / "listing.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["etsy"]["title"] = "Take A Hike Tee"
    document["etsy"]["description"] = "A retro sunset."
    path.write_text(yaml.safe_dump(document), encoding="utf-8")


# ------------------------------------------------------------ gate refusals


def test_a_gate_refusal_is_an_actionable_message_not_a_traceback(
    workspace_root: Path,
) -> None:
    """The fixture's copy is still `<generate>`, which PRD 44 refuses. The
    user needs the sentence, not a stack."""
    root = _with_shop_id(workspace_root)

    result = _plan(root, "take-a-hike")

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "<generate>" in result.output


def test_a_gate_refusal_does_not_halt_a_batch(workspace_root: Path) -> None:
    """PRD 16: continue-on-error. One listing that cannot be planned must not
    stop the rest -- which is the whole reason `--all` is safe to run."""
    root = _with_shop_id(workspace_root)
    second = root / "listings" / "second-listing"
    second.mkdir()
    source = (root / "listings" / "take-a-hike" / "listing.yaml").read_text(encoding="utf-8")
    document = yaml.safe_load(source)
    document["etsy"]["title"] = "A Real Title"
    document["etsy"]["description"] = "Real copy."
    (second / "listing.yaml").write_text(yaml.safe_dump(document), encoding="utf-8")

    result = _plan(root, "--all")

    assert "take-a-hike" in result.output
    assert "second-listing" in result.output, "the batch carried on past the refusal"
    assert result.exit_code != 0, "but the run still reports failure"
