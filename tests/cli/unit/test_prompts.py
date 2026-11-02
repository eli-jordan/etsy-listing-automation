"""Which backend asks a question, and how each one behaves.

The backend choice is not a detail. questionary cannot prompt under cygwin at
all -- prompt_toolkit builds a Win32 output and a cygwin pty has no console
screen buffer behind it -- and cygwin zsh is the shell CLAUDE.md mandates, so
the wizards have to keep working when prompt_toolkit is unavailable.

A unit layer, not a behaviour one: nothing here loads a workspace, a fake
client or a config file. It lived under ``behaviour/`` because it began in the
``new`` picker's test file, alongside the terminal-encoding tests and an
end-to-end wizard run -- three subjects, so a failure in any of them arrived
from the same place.

Every test describes its machine as a :class:`prompts.PromptHost`: which
commands a `ScriptedCliHost` has installed and how they answer, whether
prompt_toolkit can draw, and what the user types.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from etsy_listings.cli import prompts
from etsy_listings.cli.prompts import PromptHost

from tests.support.cli_host import RunAnswer, ScriptedCliHost, completed
from tests.support.doubles import replies


def _machine(
    commands: ScriptedCliHost | None = None,
    *,
    typed: Callable[[str], str] | Sequence[str] = (),
    windows: bool = False,
    toolkit: bool = False,
) -> PromptHost:
    read_line = replies(list(typed)) if not callable(typed) else typed
    return PromptHost(
        commands=commands or ScriptedCliHost(),
        windows=windows,
        prompt_toolkit=lambda: toolkit,
        read_line=read_line,
    )


def _plain(*answers: str) -> PromptHost:
    """Neither fzf nor prompt_toolkit: the numbered selector over ``input()``.

    The last resort, and the one a cygwin pty without fzf actually gets, which
    is why so much of this file runs through it.
    """
    return _machine(typed=list(answers))


def _with_fzf(answer: RunAnswer, *typed: str) -> tuple[PromptHost, ScriptedCliHost]:
    """This machine has fzf, and running it answers ``answer``."""
    commands = ScriptedCliHost(installed={"fzf": "/usr/bin/fzf"}, runs={(): answer})
    return _machine(commands, typed=list(typed)), commands


def _raising(error: type[BaseException]) -> Callable[[str], str]:
    def read(_: str) -> str:
        raise error

    return read


# --- picking a backend -------------------------------------------------------


def test_fzf_is_used_when_it_is_on_path() -> None:
    """It is what the request asked for, and -- unlike prompt_toolkit -- it
    reads its keys from /dev/tty, so it works under a cygwin pty. It is also
    the only backend that filters at all."""
    host, commands = _with_fzf(completed("row two\n"))

    assert prompts.choose("Garment", ["row one", "row two"], host=host) == "row two"
    (ran,) = commands.run_calls
    assert ran.input_text == "row one\nrow two"
    assert "/usr/bin/fzf" in ran.argv
    # fzf draws on stderr when it cannot open /dev/tty, so it stays attached.
    assert ran.capture_stderr is False
    assert ran.encoding == "utf-8"


def test_fzf_is_not_asked_for_a_height() -> None:
    """cygwin's fzf package is 0.12.1 -- the Ruby implementation -- and it
    rejects `--height` as an illegal option rather than ignoring it. Only
    flags every fzf since 2015 understands go on the command line."""
    host, commands = _with_fzf(completed("row one\n"))
    prompts.choose("Garment", ["row one"], host=host)

    assert not any(arg.startswith("--height") for arg in commands.ran[-1])


def test_cancelling_fzf_returns_none() -> None:
    host, _ = _with_fzf(completed(returncode=130))
    assert prompts.choose("Garment", ["row one"], host=host) is None


def test_an_fzf_that_cannot_run_falls_back_rather_than_looking_cancelled(capsys) -> None:
    """Status 2 is fzf failing, not the user declining. Treating it as a
    cancel would exit `new` with nothing on screen to explain why."""
    host, _ = _with_fzf(completed(returncode=2), "2")

    assert prompts.choose("Garment", ["row one", "row two"], host=host) == "row two"
    assert "status 2" in capsys.readouterr().out


def test_an_fzf_that_will_not_launch_falls_back_too(capsys) -> None:
    host, _ = _with_fzf(OSError("no such file"), "1")

    assert prompts.choose("Garment", ["row one"], host=host) == "row one"
    assert "could not run fzf" in capsys.readouterr().out


# --- finding fzf at all ------------------------------------------------------


def _cygwin(
    tmp_path: Path, runs: dict[tuple[str, ...], RunAnswer]
) -> tuple[PromptHost, ScriptedCliHost]:
    """Windows with cygwin: no native fzf, ``cygpath`` on PATH and cygwin's
    ``sh.exe`` beside it, the shell's commands answering from ``runs``."""
    (tmp_path / "sh.exe").write_text("", encoding="utf-8")
    commands = ScriptedCliHost(installed={"cygpath": str(tmp_path / "cygpath.exe")}, runs=runs)
    return _machine(commands, windows=True), commands


def test_a_native_fzf_on_path_is_used_directly() -> None:
    host = _machine(ScriptedCliHost(installed={"fzf": "C:\\bin\\fzf.exe"}), windows=True)
    assert prompts.fzf_command(host) == ["C:\\bin\\fzf.exe"]


def test_a_cygwin_fzf_script_is_run_through_cygwins_own_shell(tmp_path: Path) -> None:
    """The bug this fixes: cygwin's fzf is `/usr/bin/fzf`, a shebang script
    with no `.exe`. Native-Windows Python cannot find it with `shutil.which`
    and could not exec it if it did -- so `ls | fzf` worked in the shell while
    `new` reported no fzf at all.

    cygwin's shell is looked for beside cygpath -- the same trick
    `workspace/userpath.py` uses: cygwin hands a Windows child a translated
    PATH, so its /usr/bin is reachable as a Windows directory even though
    `/usr/bin/sh` is not a name Windows can resolve."""
    host, commands = _cygwin(tmp_path, {("-c", "command -v fzf"): completed("/usr/bin/fzf\n")})
    sh = str(tmp_path / "sh.exe")

    command = prompts.fzf_command(host)

    assert command is not None
    assert command[0] == sh
    assert 'exec fzf "$@"' in command  # the arguments stay arguments, unquoted
    assert commands.ran == [[sh, "-c", "command -v fzf"]]


def test_the_cygwin_fzf_is_what_choose_runs(tmp_path: Path) -> None:
    host, _ = _cygwin(
        tmp_path,
        {
            ("-c", "command -v fzf"): completed("/usr/bin/fzf\n"),
            ("-c", 'exec fzf "$@"'): completed("row one\n"),
        },
    )

    assert prompts.choose("Garment", ["row one"], host=host) == "row one"


@pytest.mark.parametrize(
    "probe",
    [completed(returncode=1), completed(""), OSError("nope")],
    ids=["no-fzf", "empty-answer", "probe-will-not-run"],
)
def test_a_cygwin_shell_without_a_usable_fzf_reports_no_fzf(
    tmp_path: Path, probe: RunAnswer
) -> None:
    host, _ = _cygwin(tmp_path, {("-c", "command -v fzf"): probe})
    assert prompts.fzf_command(host) is None


def test_no_native_fzf_and_no_cygpath_means_no_fzf() -> None:
    assert prompts.fzf_command(_machine(windows=True)) is None


def test_cygpath_without_a_shell_beside_it_means_no_fzf(tmp_path: Path) -> None:
    commands = ScriptedCliHost(installed={"cygpath": str(tmp_path / "cygpath.exe")})
    assert prompts.fzf_command(_machine(commands, windows=True)) is None
    assert commands.run_calls == []


def test_a_cygwin_shell_is_only_looked_for_on_windows(tmp_path: Path) -> None:
    (tmp_path / "sh.exe").write_text("", encoding="utf-8")
    commands = ScriptedCliHost(installed={"cygpath": str(tmp_path / "cygpath.exe")})
    assert prompts.fzf_command(_machine(commands, windows=False)) is None
    assert commands.run_calls == []


def test_without_fzf_prompt_toolkit_gets_a_plain_select_not_an_autocomplete(monkeypatch) -> None:
    """`questionary.select` is arrow keys over a fixed list. The autocomplete
    it replaced echoed the highlighted row into the input buffer, so arrowing
    through the list typed a query nobody asked for -- and clearing that query
    back out left a fragment matching nothing."""
    import questionary

    seen: dict[str, object] = {}

    class FakeQuestion:
        def ask(self) -> str:
            return "row two"

    def fake_select(message, **kwargs):
        seen["message"] = message
        seen.update(kwargs)
        return FakeQuestion()

    monkeypatch.setattr(questionary, "select", fake_select)
    answer = prompts.choose(
        "Garment",
        ["row one", "row two"],
        marker_hint="* = used here",
        host=_machine(toolkit=True),
    )

    assert answer == "row two"
    assert seen["choices"] == ["row one", "row two"]
    assert seen["instruction"] == "* = used here"


# --- the numbered selector ---------------------------------------------------


def test_without_fzf_or_prompt_toolkit_the_numbered_selector_runs(capsys) -> None:
    answer = prompts.choose("Garment", ["Gildan Tee", "Gildan Hoodie"], host=_plain("2"))

    assert answer == "Gildan Hoodie"
    out = capsys.readouterr().out
    assert "1  Gildan Tee" in out
    assert "2  Gildan Hoodie" in out


def test_the_numbered_selector_shows_the_marker_hint(capsys) -> None:
    prompts.choose("Garment", ["one"], marker_hint="* = used here", host=_plain("1"))
    assert "* = used here" in capsys.readouterr().out


def test_the_numbered_selector_rejects_an_out_of_range_number(capsys) -> None:
    assert prompts.choose("Garment", ["one", "two"], host=_plain("9", "1")) == "one"
    assert "no option 9" in capsys.readouterr().out


def test_text_is_not_an_answer_now_that_only_fzf_filters(capsys) -> None:
    assert prompts.choose("Garment", ["one", "two"], host=_plain("hoodie", "2")) == "two"
    assert "not a number" in capsys.readouterr().out


def test_a_long_list_pages_and_numbers_stay_absolute(capsys) -> None:
    """`n` moves a page; the numbers do not restart, so the number beside a
    row means the same thing on whichever page it is read."""
    rows = [f"row {n}" for n in range(1, prompts.PAGE_SIZE * 2 + 1)]
    host = _plain("n", str(prompts.PAGE_SIZE + 3))

    assert prompts.choose("Garment", rows, host=host) == rows[prompts.PAGE_SIZE + 2]
    out = capsys.readouterr().out
    assert "page 1/2" in out
    assert "page 2/2" in out
    assert f"row {prompts.PAGE_SIZE + 1}" in out


def test_paging_back_from_the_first_page_wraps_to_the_last(capsys) -> None:
    rows = [f"row {n}" for n in range(1, prompts.PAGE_SIZE * 2 + 1)]

    assert prompts.choose("Garment", rows, host=_plain("p", "1")) == "row 1"
    assert "page 2/2" in capsys.readouterr().out


def test_n_is_not_a_page_command_when_everything_fits_on_one_page(capsys) -> None:
    assert prompts.choose("Garment", ["one", "two"], host=_plain("n", "1")) == "one"
    out = capsys.readouterr().out
    assert "not a number" in out
    assert "page" not in out


def test_a_blank_answer_cancels() -> None:
    assert prompts.choose("Garment", ["one"], host=_plain("")) is None


def test_ctrl_c_cancels_rather_than_escaping() -> None:
    host = _machine(typed=_raising(KeyboardInterrupt))
    assert prompts.choose("Garment", ["one"], host=host) is None


def test_choosing_from_an_empty_list_is_none_not_a_crash() -> None:
    assert prompts.choose("Garment", []) is None


def test_plain_text_and_confirm_fall_back_to_input() -> None:
    assert prompts.text("Template:", default="flat-lay-01", host=_plain("")) == "flat-lay-01"
    assert prompts.confirm("Sure?", default=False, host=_plain("yes")) is True
    assert prompts.confirm("Sure?", default=True, host=_plain("")) is True


def test_plain_prompts_treat_eof_as_cancellation() -> None:
    host = _machine(typed=_raising(EOFError))
    assert prompts.text("Template:", host=host) is None
    assert prompts.confirm("Sure?", host=host) is None


def test_the_local_machine_reads_lines_through_input(monkeypatch) -> None:
    # `builtins.input` is looked up per call, so wizard tests that redirect it
    # still reach the plain backend through the default host.
    monkeypatch.setattr("builtins.input", replies(["typed"]))
    assert prompts.LOCAL_PROMPT_HOST.read_line("> ") == "typed"


# --- declining, as the wizards see it ----------------------------------------
#
# `choose`/`text`/`confirm` answer None; `pick`/`ask_*` raise. The wizards use
# the raising pair, so that a question nobody remembered to check cannot pass
# a None off as an answer.


def test_pick_offers_each_option_by_its_label_and_maps_the_answer_back() -> None:
    options = [("gildan", 5000), ("comfort", 1717)]

    assert prompts.pick("Garment", options, label=lambda o: o[0], host=_plain("2")) == (
        "comfort",
        1717,
    )


def test_declining_any_of_the_raising_prompts_is_cancellation() -> None:
    host = _plain("", "", "")

    with pytest.raises(prompts.Cancelled):
        prompts.ask_choice("Garment", ["one"], host=host)
    with pytest.raises(prompts.Cancelled):
        prompts.pick("Garment", ["one"], host=host)
    with pytest.raises(prompts.Cancelled):
        prompts.ask_text("Name:", host=host)
    with pytest.raises(prompts.Cancelled):
        prompts.ask_confirm("Sure?", host=_machine(typed=_raising(EOFError)))


def test_a_blank_text_answer_is_declining_unless_blank_was_offered() -> None:
    """Most questions want a name and "" is not one. The exceptions say so --
    "Preferred print provider (blank for none)" means it."""
    with pytest.raises(prompts.Cancelled):
        prompts.ask_text("Pricing plan name:", host=_plain(""))

    assert prompts.ask_text("Print provider:", allow_blank=True, host=_plain("")) == ""


def test_answering_no_is_an_answer_not_a_cancellation() -> None:
    assert prompts.ask_confirm("Sure?", default=True, host=_plain("n")) is False
