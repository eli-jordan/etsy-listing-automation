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
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from etsy_listings import prompts

from tests.support.doubles import FakeRun, replies


@pytest.fixture
def fzf(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201 - returns a local installer
    """This machine has fzf, and ``subprocess.run`` answers as the test says."""
    monkeypatch.setattr(prompts, "fzf_command", lambda: ["/usr/bin/fzf"])

    def answers(**kwargs: object) -> FakeRun:
        fake = FakeRun(**kwargs)  # type: ignore[arg-type]
        monkeypatch.setattr(prompts.subprocess, "run", fake)
        return fake

    return answers


@pytest.fixture
def plain(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201 - returns a local installer
    """Neither fzf nor prompt_toolkit: the numbered selector over ``input()``.

    The last resort, and the one a cygwin pty without fzf actually gets, which
    is why so much of this file runs through it.
    """
    monkeypatch.setattr(prompts, "fzf_command", lambda: None)
    monkeypatch.setattr(prompts, "prompt_toolkit_works", lambda: False)

    def types(*answers: str) -> None:
        monkeypatch.setattr("builtins.input", replies(list(answers)))

    return types


# --- picking a backend -------------------------------------------------------


def test_fzf_is_used_when_it_is_on_path(fzf) -> None:
    """It is what the request asked for, and -- unlike prompt_toolkit -- it
    reads its keys from /dev/tty, so it works under a cygwin pty. It is also
    the only backend that filters at all."""
    ran = fzf(stdout="row two\n")

    assert prompts.choose("Garment", ["row one", "row two"]) == "row two"
    assert ran.stdin == "row one\nrow two"
    assert "/usr/bin/fzf" in ran.args


def test_fzf_is_not_asked_for_a_height(fzf) -> None:
    """cygwin's fzf package is 0.12.1 -- the Ruby implementation -- and it
    rejects `--height` as an illegal option rather than ignoring it. Only
    flags every fzf since 2015 understands go on the command line."""
    ran = fzf(stdout="row one\n")
    prompts.choose("Garment", ["row one"])

    assert not any(arg.startswith("--height") for arg in ran.args)


def test_cancelling_fzf_returns_none(fzf) -> None:
    fzf(returncode=130)
    assert prompts.choose("Garment", ["row one"]) is None


def test_an_fzf_that_cannot_run_falls_back_rather_than_looking_cancelled(
    monkeypatch, fzf, capsys
) -> None:
    """Status 2 is fzf failing, not the user declining. Treating it as a
    cancel would exit `new` with nothing on screen to explain why."""
    monkeypatch.setattr(prompts, "prompt_toolkit_works", lambda: False)
    monkeypatch.setattr("builtins.input", replies(["2"]))
    fzf(returncode=2)

    assert prompts.choose("Garment", ["row one", "row two"]) == "row two"
    assert "status 2" in capsys.readouterr().out


def test_an_fzf_that_will_not_launch_falls_back_too(monkeypatch, fzf, capsys) -> None:
    monkeypatch.setattr(prompts, "prompt_toolkit_works", lambda: False)
    monkeypatch.setattr("builtins.input", replies(["1"]))
    fzf(error=OSError("no such file"))

    assert prompts.choose("Garment", ["row one"]) == "row one"
    assert "could not run fzf" in capsys.readouterr().out


# --- finding fzf at all ------------------------------------------------------


def test_a_native_fzf_on_path_is_used_directly(monkeypatch) -> None:
    monkeypatch.setattr(prompts.shutil, "which", lambda name: "C:\\bin\\fzf.exe")
    assert prompts.fzf_command.__wrapped__() == ["C:\\bin\\fzf.exe"]


def test_a_cygwin_fzf_script_is_run_through_cygwins_own_shell(monkeypatch) -> None:
    """The bug this fixes: cygwin's fzf is `/usr/bin/fzf`, a shebang script
    with no `.exe`. Native-Windows Python cannot find it with `shutil.which`
    and could not exec it if it did -- so `ls | fzf` worked in the shell while
    `new` reported no fzf at all."""
    monkeypatch.setattr(prompts.shutil, "which", lambda name: None)
    monkeypatch.setattr(prompts, "_cygwin_sh", lambda: "C:\\cygwin64\\bin\\sh.exe")
    ran = FakeRun(stdout="/usr/bin/fzf\n")
    monkeypatch.setattr(prompts.subprocess, "run", ran)

    command = prompts.fzf_command.__wrapped__()

    assert command is not None
    assert command[0] == "C:\\cygwin64\\bin\\sh.exe"
    assert 'exec fzf "$@"' in command  # the arguments stay arguments, unquoted
    assert ran.args == ["C:\\cygwin64\\bin\\sh.exe", "-c", "command -v fzf"]


def test_a_cygwin_shell_without_fzf_reports_no_fzf(monkeypatch) -> None:
    monkeypatch.setattr(prompts.shutil, "which", lambda name: None)
    monkeypatch.setattr(prompts, "_cygwin_sh", lambda: "C:\\cygwin64\\bin\\sh.exe")
    monkeypatch.setattr(prompts.subprocess, "run", FakeRun(returncode=1))

    assert prompts.fzf_command.__wrapped__() is None


def test_a_probe_that_will_not_run_reports_no_fzf(monkeypatch) -> None:
    monkeypatch.setattr(prompts.shutil, "which", lambda name: None)
    monkeypatch.setattr(prompts, "_cygwin_sh", lambda: "C:\\cygwin64\\bin\\sh.exe")
    monkeypatch.setattr(prompts.subprocess, "run", FakeRun(error=OSError("nope")))

    assert prompts.fzf_command.__wrapped__() is None


def test_no_native_fzf_and_no_cygwin_means_no_fzf(monkeypatch) -> None:
    monkeypatch.setattr(prompts.shutil, "which", lambda name: None)
    monkeypatch.setattr(prompts, "_cygwin_sh", lambda: None)
    assert prompts.fzf_command.__wrapped__() is None


def _pretend_os_name(monkeypatch, name: str) -> None:
    """Give `prompts` a stand-in `os`, rather than reaching into the real one.

    `monkeypatch.setattr(prompts.os, "name", ...)` mutates the `os` module
    itself, and pathlib picks `WindowsPath` over `PosixPath` off `os.name` --
    so faking "nt" on a POSIX machine makes the next `Path(...)` raise
    `NotImplementedError` instead of exercising the branch under test.
    """
    monkeypatch.setattr(prompts, "os", SimpleNamespace(name=name))


def test_cygwins_shell_is_looked_for_beside_cygpath(monkeypatch, tmp_path: Path) -> None:
    """The same trick `workspace/userpath.py` uses: cygwin hands a Windows
    child a translated PATH, so its /usr/bin is reachable as a Windows
    directory even though `/usr/bin/sh` is not a name Windows can resolve."""
    (tmp_path / "sh.exe").write_text("", encoding="utf-8")
    _pretend_os_name(monkeypatch, "nt")
    monkeypatch.setattr(prompts.shutil, "which", lambda name: str(tmp_path / "cygpath.exe"))
    assert prompts._cygwin_sh() == str(tmp_path / "sh.exe")


def test_no_cygpath_means_no_cygwin_shell(monkeypatch) -> None:
    _pretend_os_name(monkeypatch, "nt")
    monkeypatch.setattr(prompts.shutil, "which", lambda name: None)
    assert prompts._cygwin_sh() is None


def test_a_cygwin_shell_is_only_looked_for_on_windows(monkeypatch) -> None:
    _pretend_os_name(monkeypatch, "posix")
    assert prompts._cygwin_sh() is None


def test_without_fzf_prompt_toolkit_gets_a_plain_select_not_an_autocomplete(monkeypatch) -> None:
    """`questionary.select` is arrow keys over a fixed list. The autocomplete
    it replaced echoed the highlighted row into the input buffer, so arrowing
    through the list typed a query nobody asked for -- and clearing that query
    back out left a fragment matching nothing."""
    import questionary

    monkeypatch.setattr(prompts, "fzf_command", lambda: None)
    monkeypatch.setattr(prompts, "prompt_toolkit_works", lambda: True)
    seen: dict[str, object] = {}

    class FakeQuestion:
        def ask(self) -> str:
            return "row two"

    def fake_select(message, **kwargs):
        seen["message"] = message
        seen.update(kwargs)
        return FakeQuestion()

    monkeypatch.setattr(questionary, "select", fake_select)
    answer = prompts.choose("Garment", ["row one", "row two"], marker_hint="* = used here")

    assert answer == "row two"
    assert seen["choices"] == ["row one", "row two"]
    assert seen["instruction"] == "* = used here"


# --- the numbered selector ---------------------------------------------------


def test_without_fzf_or_prompt_toolkit_the_numbered_selector_runs(plain, capsys) -> None:
    plain("2")

    answer = prompts.choose("Garment", ["Gildan Tee", "Gildan Hoodie"])

    assert answer == "Gildan Hoodie"
    out = capsys.readouterr().out
    assert "1  Gildan Tee" in out
    assert "2  Gildan Hoodie" in out


def test_the_numbered_selector_shows_the_marker_hint(plain, capsys) -> None:
    plain("1")
    prompts.choose("Garment", ["one"], marker_hint="* = used here")
    assert "* = used here" in capsys.readouterr().out


def test_the_numbered_selector_rejects_an_out_of_range_number(plain, capsys) -> None:
    plain("9", "1")
    assert prompts.choose("Garment", ["one", "two"]) == "one"
    assert "no option 9" in capsys.readouterr().out


def test_text_is_not_an_answer_now_that_only_fzf_filters(plain, capsys) -> None:
    plain("hoodie", "2")
    assert prompts.choose("Garment", ["one", "two"]) == "two"
    assert "not a number" in capsys.readouterr().out


def test_a_long_list_pages_and_numbers_stay_absolute(plain, capsys) -> None:
    """`n` moves a page; the numbers do not restart, so the number beside a
    row means the same thing on whichever page it is read."""
    rows = [f"row {n}" for n in range(1, prompts.PAGE_SIZE * 2 + 1)]
    plain("n", str(prompts.PAGE_SIZE + 3))

    assert prompts.choose("Garment", rows) == rows[prompts.PAGE_SIZE + 2]
    out = capsys.readouterr().out
    assert "page 1/2" in out
    assert "page 2/2" in out
    assert f"row {prompts.PAGE_SIZE + 1}" in out


def test_paging_back_from_the_first_page_wraps_to_the_last(plain, capsys) -> None:
    rows = [f"row {n}" for n in range(1, prompts.PAGE_SIZE * 2 + 1)]
    plain("p", "1")

    assert prompts.choose("Garment", rows) == "row 1"
    assert "page 2/2" in capsys.readouterr().out


def test_n_is_not_a_page_command_when_everything_fits_on_one_page(plain, capsys) -> None:
    plain("n", "1")
    assert prompts.choose("Garment", ["one", "two"]) == "one"
    out = capsys.readouterr().out
    assert "not a number" in out
    assert "page" not in out


def test_a_blank_answer_cancels(plain) -> None:
    plain("")
    assert prompts.choose("Garment", ["one"]) is None


def test_ctrl_c_cancels_rather_than_escaping(monkeypatch, plain) -> None:
    def interrupt(_: str) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupt)
    assert prompts.choose("Garment", ["one"]) is None


def test_choosing_from_an_empty_list_is_none_not_a_crash() -> None:
    assert prompts.choose("Garment", []) is None


def test_plain_text_and_confirm_fall_back_to_input(plain) -> None:
    plain("")
    assert prompts.text("Template:", default="flat-lay-01") == "flat-lay-01"

    plain("yes")
    assert prompts.confirm("Sure?", default=False) is True

    plain("")
    assert prompts.confirm("Sure?", default=True) is True


def test_plain_prompts_treat_eof_as_cancellation(monkeypatch, plain) -> None:
    def eof(_: str) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert prompts.text("Template:") is None
    assert prompts.confirm("Sure?") is None


# --- declining, as the wizards see it ----------------------------------------
#
# `choose`/`text`/`confirm` answer None; `pick`/`ask_*` raise. The wizards use
# the raising pair, so that a question nobody remembered to check cannot pass
# a None off as an answer.


def test_pick_offers_each_option_by_its_label_and_maps_the_answer_back(plain) -> None:
    plain("2")
    options = [("gildan", 5000), ("comfort", 1717)]

    assert prompts.pick("Garment", options, label=lambda o: o[0]) == ("comfort", 1717)


def test_declining_any_of_the_raising_prompts_is_cancellation(monkeypatch, plain) -> None:
    plain("", "", "")

    with pytest.raises(prompts.Cancelled):
        prompts.ask_choice("Garment", ["one"])
    with pytest.raises(prompts.Cancelled):
        prompts.pick("Garment", ["one"])
    with pytest.raises(prompts.Cancelled):
        prompts.ask_text("Name:")

    monkeypatch.setattr(prompts, "confirm", lambda *a, **k: None)
    with pytest.raises(prompts.Cancelled):
        prompts.ask_confirm("Sure?")


def test_a_blank_text_answer_is_declining_unless_blank_was_offered(plain) -> None:
    """Most questions want a name and "" is not one. The exceptions say so --
    "Preferred print provider (blank for none)" means it."""
    plain("")
    with pytest.raises(prompts.Cancelled):
        prompts.ask_text("Pricing plan name:")

    plain("")
    assert prompts.ask_text("Print provider:", allow_blank=True) == ""


def test_answering_no_is_an_answer_not_a_cancellation(plain) -> None:
    plain("n")
    assert prompts.ask_confirm("Sure?", default=True) is False
