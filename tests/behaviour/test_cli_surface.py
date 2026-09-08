"""What the CLI actually shows: the help surface (every flag, and the
environment variables that configure the tool), the plan report, and the
progress lines `apply` prints.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from etsy_listings import prompts
from etsy_listings.cli import app as cli
from etsy_listings.cli.app import app
from etsy_listings.engine.context import Event

runner = CliRunner()


ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _help(*args: str) -> str:
    """The help text, with styling stripped.

    rich turns colour on by itself when it detects CI, and its option
    highlighter styles the leading dash as its own span -- so `--root` reaches
    the buffer as `\x1b[1m-\x1b[0m\x1b[1m-root\x1b[0m` and a substring search
    for the flag finds nothing. These assertions are about what the help
    documents, not how it is painted.
    """
    result = runner.invoke(app, [*args, "--help"])
    assert result.exit_code == 0, result.output
    return ANSI.sub("", result.output)


def test_top_level_help_documents_every_environment_variable() -> None:
    output = _help()
    for variable in (
        "ETSY_LISTINGS_ROOT",
        "PRINTIFY_API_TOKEN",
        "ANTHROPIC_API_KEY",
        "NO_COLOR",
        "FORCE_COLOR",
    ):
        assert variable in output, f"{variable} missing from --help"


def test_top_level_help_lists_every_command() -> None:
    output = _help()
    for command in ("setup", "plan", "apply", "new", "ui"):
        assert command in output


@pytest.mark.parametrize("command", ["setup", "plan", "apply", "new", "ui"])
def test_every_command_documents_root_and_its_environment_variable(command: str) -> None:
    output = _help(command)
    assert "--root" in output
    assert "ETSY_LISTINGS_ROOT" in output


def test_command_help_documents_the_command_specific_flags() -> None:
    assert "--all" in _help("plan")
    assert "--all" in _help("apply")
    assert "--category" in _help("new")
    ui_help = _help("ui")
    assert "--host" in ui_help
    assert "--port" in ui_help


def test_root_can_be_given_through_the_environment(workspace_root: Path) -> None:
    result = runner.invoke(
        app, ["plan", "take-a-hike"], env={"ETSY_LISTINGS_ROOT": str(workspace_root)}
    )
    assert result.exit_code == 0, result.output
    assert "+ render" in result.output


def test_plan_output_names_the_inputs_and_outputs(workspace_root: Path) -> None:
    result = runner.invoke(app, ["plan", "take-a-hike", "--root", str(workspace_root)])
    assert result.exit_code == 0, result.output
    assert "render flat-lay-01/black" in result.output
    assert "in   designs/take-a-hike.png" in result.output
    assert "out  .cache/renders/take-a-hike/flat-lay-01/black.png" in result.output
    assert "1 to run (4 actions)" in result.output


def test_plan_marks_a_missing_render_in_its_output(workspace_root: Path) -> None:
    applied = runner.invoke(app, ["apply", "take-a-hike", "--root", str(workspace_root)])
    assert applied.exit_code == 0, applied.output
    (workspace_root / ".cache/renders/take-a-hike/flat-lay-01/ivory.png").unlink()

    result = runner.invoke(app, ["plan", "take-a-hike", "--root", str(workspace_root)])
    assert "1 rendered file missing from the cache" in result.output
    assert "ivory.png   (missing)" in result.output


def test_a_clean_workspace_plans_as_no_changes(workspace_root: Path) -> None:
    runner.invoke(app, ["apply", "take-a-hike", "--root", str(workspace_root)])
    result = runner.invoke(app, ["plan", "take-a-hike", "--root", str(workspace_root)])
    assert "No changes." in result.output
    assert "0 to run," in result.output


def test_new_without_a_token_explains_what_to_do(workspace_root: Path, monkeypatch) -> None:
    """The reported failure was a raw httpx `401 Unauthorized` traceback out of
    `blueprints()`. The catalog needs a token; not having one is a setup step,
    not a crash. A design the fixture has no listing for, so the run reaches
    the catalog rather than stopping at the already-exists guard."""
    monkeypatch.delenv("PRINTIFY_API_TOKEN", raising=False)
    result = runner.invoke(app, ["new", "second-design", "--root", str(workspace_root)])

    assert result.exit_code == 1
    assert "PRINTIFY_API_TOKEN" in result.output
    assert "catalog.read" in result.output
    assert str(workspace_root) in result.output


@pytest.fixture
def plain_env(monkeypatch):
    for variable in ("NO_COLOR", "FORCE_COLOR"):
        monkeypatch.delenv(variable, raising=False)
    return monkeypatch


def test_swatches_are_dropped_when_stdout_is_not_a_terminal(plain_env, capsys) -> None:
    """A redirected run would otherwise collect a column of identical,
    meaningless blocks -- click strips the colour that gave them meaning."""
    cli._echo_event(Event(message="rendered flat-lay-01/black", swatches=((10, 20, 30),)))
    assert capsys.readouterr().out == "  rendered flat-lay-01/black\n"


def test_no_color_suppresses_the_swatch(plain_env) -> None:
    plain_env.setenv("NO_COLOR", "1")
    assert cli._swatch_glyph() is None


def test_force_color_overrides_the_non_terminal_check(plain_env) -> None:
    """A cygwin pty is a named pipe: native-Windows Python reports isatty()
    false inside one, even though the terminal renders colour fine."""
    plain_env.setenv("FORCE_COLOR", "1")
    assert cli._swatch_glyph() == cli.SWATCH_GLYPH


def test_no_color_wins_over_force_color(plain_env) -> None:
    plain_env.setenv("FORCE_COLOR", "1")
    plain_env.setenv("NO_COLOR", "1")
    assert cli._swatch_glyph() is None


def test_a_stdout_that_cannot_encode_the_block_falls_back_to_ascii(plain_env) -> None:
    """cp1252 cannot encode the block glyph -- that used to abort `apply` with
    a UnicodeEncodeError. The colour is the part that matters, so keep it and
    change the character."""
    plain_env.setenv("FORCE_COLOR", "1")
    plain_env.setattr(cli.sys, "stdout", _FakeStdout("cp1252"))
    assert cli._swatch_glyph() == cli.SWATCH_FALLBACK


def test_an_unknown_stdout_encoding_still_yields_a_swatch(plain_env) -> None:
    plain_env.setenv("FORCE_COLOR", "1")
    plain_env.setattr(cli.sys, "stdout", _FakeStdout("not-a-real-codec"))
    assert cli._swatch_glyph() == cli.SWATCH_FALLBACK


class _FakeStdout:
    def __init__(self, encoding: str) -> None:
        self.encoding = encoding

    def isatty(self) -> bool:
        return True


def test_each_swatch_is_styled_with_the_colour_the_stage_sampled(plain_env, capsys) -> None:
    """One block per garment, in the colour that scene actually rendered."""
    plain_env.setattr(cli, "_swatch_glyph", lambda: cli.SWATCH_GLYPH)
    styled: list[tuple[str, object]] = []

    def fake_style(text: str, fg: object = None, **kwargs: object) -> str:
        styled.append((text, fg))
        return text

    plain_env.setattr(cli.typer, "style", fake_style)
    cli._echo_event(
        Event(message="rendered colour-chart-01", swatches=((10, 20, 30), (200, 100, 50)))
    )

    assert styled == [(cli.SWATCH_GLYPH, (10, 20, 30)), (cli.SWATCH_GLYPH, (200, 100, 50))]
    assert capsys.readouterr().out.endswith(" rendered colour-chart-01\n")


def test_the_ansi_escapes_survive_to_the_terminal(plain_env, capsys) -> None:
    """click strips ANSI when it thinks stdout is not a terminal -- which would
    silently undo the decision `_swatch_glyph` just made."""
    plain_env.setenv("FORCE_COLOR", "1")
    cli._echo_event(Event(message="rendered flat-lay-01/black", swatches=((10, 20, 30),)))
    assert "38;2;10;20;30" in capsys.readouterr().out


def test_an_event_with_no_swatch_is_printed_plainly(capsys) -> None:
    cli._echo_event(Event(message="applying render"))
    assert capsys.readouterr().out == "  applying render\n"


def test_new_takes_no_design_and_offers_a_picker(workspace_root: Path, monkeypatch) -> None:
    """`new` is a wizard: the design is picked from `designs/` like every
    other answer, so the argument is optional."""
    monkeypatch.delenv("PRINTIFY_API_TOKEN", raising=False)
    asked: list[tuple[str, list[str]]] = []

    def fake_choose(message: str, rows, **kwargs: object) -> str:
        asked.append((message, list(rows)))
        return list(rows)[0]

    monkeypatch.setattr(prompts, "choose", fake_choose)
    (workspace_root / "designs" / "brand-new.png").write_bytes(b"")

    result = runner.invoke(app, ["new", "--root", str(workspace_root)])

    assert asked and asked[0][0] == "Design"
    assert any(row.endswith("brand-new") for row in asked[0][1])
    # Stopped at the catalog, i.e. the design question was answered without one.
    assert "PRINTIFY_API_TOKEN" in result.output


def test_new_refuses_a_design_that_already_has_a_listing(workspace_root: Path, monkeypatch) -> None:
    """Before, this ran the whole wizard and failed on the final write."""
    monkeypatch.delenv("PRINTIFY_API_TOKEN", raising=False)
    result = runner.invoke(app, ["new", "take-a-hike", "--root", str(workspace_root)])

    assert result.exit_code == 1
    assert "a listing already exists" in result.output
    assert "PRINTIFY_API_TOKEN" not in result.output


def test_new_without_any_designs_says_where_to_put_one(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("PRINTIFY_API_TOKEN", raising=False)
    (tmp_path / "shop.yaml").write_text(
        "etsy:\n  shop_id: 1\n  who_made: i_did\n  when_made: made_to_order\n"
        "  is_supply: false\ncurrency: NOK\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["new", "--root", str(tmp_path)])

    assert result.exit_code == 1
    assert "no designs under" in result.output
