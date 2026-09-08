"""The garment picker: how rows are built, and which backend asks the question.

The backend choice is not a detail. questionary cannot prompt under cygwin at
all -- prompt_toolkit builds a Win32 output and a cygwin pty has no console
screen buffer behind it -- and cygwin zsh is the shell CLAUDE.md mandates, so
`new` has to keep working when prompt_toolkit is unavailable.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from etsy_listings import prompts, terminal
from etsy_listings.clients.printify.models import Blueprint
from etsy_listings.clients.printify.resolve import normalise
from etsy_listings.newcmd.logic import (
    LOCAL_MARKER,
    LOCAL_MARKER_FALLBACK,
    build_blueprint_choices,
    local_blueprint_keys,
)
from etsy_listings.workspace.workspace import Workspace

COMFORT_TEE = Blueprint(
    id=6, title="Unisex Garment-Dyed Heavy Weight Tee", brand="Comfort Colors", model="1717"
)
GILDAN_TEE = Blueprint(id=12, title="Unisex Heavy Cotton Tee", brand="Gildan", model="5000")


def _key(blueprint: Blueprint) -> tuple[str, str]:
    """A blueprint as `local_blueprint_keys` reports it: normalised brand+model."""
    return (normalise(blueprint.brand), normalise(blueprint.model))


GILDAN_HOODIE = Blueprint(id=99, title="Unisex Pullover Hoodie", brand="Gildan", model="18500")
GILDAN_LONG = Blueprint(id=13, title="Unisex Long Sleeve Tee", brand="Gildan", model="2400")
ALL = [COMFORT_TEE, GILDAN_HOODIE, GILDAN_TEE, GILDAN_LONG]


# --- the rows themselves -----------------------------------------------------


def test_locally_used_garments_come_first_and_carry_the_marker() -> None:
    choices = build_blueprint_choices(ALL, {_key(GILDAN_HOODIE)}, marker="* ")

    assert choices[0].blueprint == GILDAN_HOODIE
    assert choices[0].is_local is True
    assert choices[0].label.startswith("* ")
    assert all(not choice.is_local for choice in choices[1:])


def test_rows_carry_brand_model_and_title_as_aligned_columns() -> None:
    """Brand and model, not an inferred garment type: "Gildan 18500" is what
    identifies a blank, and Printify supplies it rather than us guessing."""
    choices = build_blueprint_choices(ALL, set(), marker="* ")
    labels = [choice.label for choice in choices]

    for choice in choices:
        assert choice.blueprint.brand in choice.label
        assert choice.blueprint.model in choice.label
        assert choice.blueprint.title in choice.label

    # Every row puts the title at the same column, which is what makes the
    # list scannable rather than ragged.
    title_columns = {
        label.index(c.blueprint.title) for label, c in zip(labels, choices, strict=True)
    }
    assert len(title_columns) == 1


def test_the_model_column_sits_between_the_brand_and_the_title() -> None:
    label = build_blueprint_choices([GILDAN_HOODIE], set(), marker="* ")[0].label
    assert label.index("Gildan") < label.index("18500") < label.index("Unisex Pullover Hoodie")


def test_rows_without_a_local_profile_still_reserve_the_marker_column() -> None:
    choices = build_blueprint_choices(ALL, {_key(GILDAN_HOODIE)}, marker="* ")
    marked, unmarked = choices[0], choices[1]
    assert marked.label.index(marked.blueprint.brand) == unmarked.label.index(
        unmarked.blueprint.brand
    )


def test_within_a_group_rows_sort_by_brand_then_title() -> None:
    choices = build_blueprint_choices(ALL, set(), marker="* ")
    assert [(c.blueprint.brand, c.blueprint.title) for c in choices] == [
        ("Comfort Colors", "Unisex Garment-Dyed Heavy Weight Tee"),
        ("Gildan", "Unisex Heavy Cotton Tee"),
        ("Gildan", "Unisex Long Sleeve Tee"),
        ("Gildan", "Unisex Pullover Hoodie"),
    ]


def test_no_blueprints_produces_no_rows() -> None:
    assert build_blueprint_choices([], set()) == []


# --- which garments count as "already used here" -----------------------------


def test_local_blueprint_keys_reads_the_workspace_profiles(workspace_root: Path) -> None:
    """The fixture workspace holds one profile, `comfort-colors-1717`, whose
    `blueprint:` says `brand: Comfort Colors` / `model: "1717"`.

    Written out as a literal. Deriving the expected set the way the code does
    -- `normalise(profile.blueprint.brand)` over `profile_names()` -- passes
    for *any* behaviour `normalise` might have, including none: both sides move
    together, so the assertion can never disagree with the implementation. The
    casefolding it is really claiming is only visible when one side is fixed.
    """
    workspace = Workspace.discover(root_override=workspace_root)

    assert local_blueprint_keys(workspace) == {("comfort colors", "1717")}


def test_a_local_key_ignores_case_and_the_trademark_sign(workspace_root: Path) -> None:
    """The catalog says "Comfort Colors®"; a hand-written profile says
    "Comfort Colors". The marker has to survive that, or the garment you used
    yesterday stops sorting to the top for a reason nobody can see."""
    workspace = Workspace.discover(root_override=workspace_root)
    catalog_entry = Blueprint(
        id=706, title="Unisex Garment-Dyed T-shirt", brand="Comfort Colors®", model="1717"
    )
    choices = build_blueprint_choices([catalog_entry], local_blueprint_keys(workspace))
    assert choices[0].is_local is True


def test_a_broken_profile_costs_a_marker_not_the_whole_picker(workspace_root: Path) -> None:
    (workspace_root / "profiles" / "broken.yaml").write_text("not: a profile\n", encoding="utf-8")
    workspace = Workspace.discover(root_override=workspace_root)
    assert local_blueprint_keys(workspace)  # the valid ones still resolve


def test_a_workspace_with_no_profiles_directory_has_no_local_keys(tmp_path: Path) -> None:
    (tmp_path / "shop.yaml").write_text(
        "etsy:\n  shop_id: 1\n  who_made: i_did\n  when_made: made_to_order\n"
        "  is_supply: false\ncurrency: NOK\n",
        encoding="utf-8",
    )
    workspace = Workspace.discover(root_override=tmp_path)
    assert workspace.profile_names() == []
    assert local_blueprint_keys(workspace) == set()


# --- picking a backend -------------------------------------------------------


def test_fzf_is_used_when_it_is_on_path(monkeypatch) -> None:
    """It is what the request asked for, and -- unlike prompt_toolkit -- it
    reads its keys from /dev/tty, so it works under a cygwin pty. It is also
    the only backend that filters at all."""
    monkeypatch.setattr(prompts, "fzf_command", lambda: ["/usr/bin/fzf"])
    seen: dict[str, object] = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        seen["input"] = kwargs["input"]
        return subprocess.CompletedProcess(args, 0, stdout="row two\n")

    monkeypatch.setattr(prompts.subprocess, "run", fake_run)
    assert prompts.choose("Garment", ["row one", "row two"]) == "row two"
    assert seen["input"] == "row one\nrow two"
    assert "/usr/bin/fzf" in seen["args"]  # type: ignore[operator]


def test_fzf_is_not_asked_for_a_height(monkeypatch) -> None:
    """cygwin's fzf package is 0.12.1 -- the Ruby implementation -- and it
    rejects `--height` as an illegal option rather than ignoring it. Only
    flags every fzf since 2015 understands go on the command line."""
    monkeypatch.setattr(prompts, "fzf_command", lambda: ["/usr/bin/fzf"])
    seen: dict[str, object] = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        return subprocess.CompletedProcess(args, 0, stdout="row one\n")

    monkeypatch.setattr(prompts.subprocess, "run", fake_run)
    prompts.choose("Garment", ["row one"])

    assert not any(str(arg).startswith("--height") for arg in seen["args"])  # type: ignore[union-attr]


def test_cancelling_fzf_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(prompts, "fzf_command", lambda: ["/usr/bin/fzf"])
    monkeypatch.setattr(
        prompts.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 130, stdout=""),
    )
    assert prompts.choose("Garment", ["row one"]) is None


def test_an_fzf_that_cannot_run_falls_back_rather_than_looking_cancelled(
    monkeypatch, capsys
) -> None:
    """Status 2 is fzf failing, not the user declining. Treating it as a
    cancel would exit `new` with nothing on screen to explain why."""
    monkeypatch.setattr(prompts, "fzf_command", lambda: ["/usr/bin/fzf"])
    monkeypatch.setattr(prompts, "prompt_toolkit_works", lambda: False)
    monkeypatch.setattr(
        prompts.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 2, stdout=""),
    )
    monkeypatch.setattr("builtins.input", _replies(["2"]))

    assert prompts.choose("Garment", ["row one", "row two"]) == "row two"
    assert "status 2" in capsys.readouterr().out


def test_an_fzf_that_will_not_launch_falls_back_too(monkeypatch, capsys) -> None:
    monkeypatch.setattr(prompts, "fzf_command", lambda: ["/usr/bin/fzf"])
    monkeypatch.setattr(prompts, "prompt_toolkit_works", lambda: False)

    def explode(args, **kwargs):
        raise OSError("no such file")

    monkeypatch.setattr(prompts.subprocess, "run", explode)
    monkeypatch.setattr("builtins.input", _replies(["1"]))

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
    seen: dict[str, object] = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        return subprocess.CompletedProcess(args, 0, stdout="/usr/bin/fzf\n")

    monkeypatch.setattr(prompts.subprocess, "run", fake_run)
    command = prompts.fzf_command.__wrapped__()

    assert command is not None
    assert command[0] == "C:\\cygwin64\\bin\\sh.exe"
    assert 'exec fzf "$@"' in command  # the arguments stay arguments, unquoted
    assert seen["args"] == ["C:\\cygwin64\\bin\\sh.exe", "-c", "command -v fzf"]


def test_a_cygwin_shell_without_fzf_reports_no_fzf(monkeypatch) -> None:
    monkeypatch.setattr(prompts.shutil, "which", lambda name: None)
    monkeypatch.setattr(prompts, "_cygwin_sh", lambda: "C:\\cygwin64\\bin\\sh.exe")
    monkeypatch.setattr(
        prompts.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 1, stdout=""),
    )
    assert prompts.fzf_command.__wrapped__() is None


def test_a_probe_that_will_not_run_reports_no_fzf(monkeypatch) -> None:
    monkeypatch.setattr(prompts.shutil, "which", lambda name: None)
    monkeypatch.setattr(prompts, "_cygwin_sh", lambda: "C:\\cygwin64\\bin\\sh.exe")

    def explode(args, **kwargs):
        raise OSError("nope")

    monkeypatch.setattr(prompts.subprocess, "run", explode)
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


def test_without_fzf_or_prompt_toolkit_the_numbered_selector_runs(monkeypatch, capsys) -> None:
    monkeypatch.setattr(prompts, "fzf_command", lambda: None)
    monkeypatch.setattr(prompts, "prompt_toolkit_works", lambda: False)
    monkeypatch.setattr("builtins.input", _replies(["2"]))

    answer = prompts.choose("Garment", ["Gildan Tee", "Gildan Hoodie"])

    assert answer == "Gildan Hoodie"
    out = capsys.readouterr().out
    assert "1  Gildan Tee" in out
    assert "2  Gildan Hoodie" in out


def test_the_numbered_selector_shows_the_marker_hint(monkeypatch, capsys) -> None:
    monkeypatch.setattr(prompts, "fzf_command", lambda: None)
    monkeypatch.setattr(prompts, "prompt_toolkit_works", lambda: False)
    monkeypatch.setattr("builtins.input", _replies(["1"]))
    prompts.choose("Garment", ["one"], marker_hint="* = used here")
    assert "* = used here" in capsys.readouterr().out


def test_the_numbered_selector_rejects_an_out_of_range_number(monkeypatch, capsys) -> None:
    monkeypatch.setattr(prompts, "fzf_command", lambda: None)
    monkeypatch.setattr(prompts, "prompt_toolkit_works", lambda: False)
    monkeypatch.setattr("builtins.input", _replies(["9", "1"]))
    assert prompts.choose("Garment", ["one", "two"]) == "one"
    assert "no option 9" in capsys.readouterr().out


def test_text_is_not_an_answer_now_that_only_fzf_filters(monkeypatch, capsys) -> None:
    monkeypatch.setattr(prompts, "fzf_command", lambda: None)
    monkeypatch.setattr(prompts, "prompt_toolkit_works", lambda: False)
    monkeypatch.setattr("builtins.input", _replies(["hoodie", "2"]))
    assert prompts.choose("Garment", ["one", "two"]) == "two"
    assert "not a number" in capsys.readouterr().out


def test_a_long_list_pages_and_numbers_stay_absolute(monkeypatch, capsys) -> None:
    """`n` moves a page; the numbers do not restart, so the number beside a
    row means the same thing on whichever page it is read."""
    monkeypatch.setattr(prompts, "fzf_command", lambda: None)
    monkeypatch.setattr(prompts, "prompt_toolkit_works", lambda: False)
    rows = [f"row {n}" for n in range(1, prompts.PAGE_SIZE * 2 + 1)]
    monkeypatch.setattr("builtins.input", _replies(["n", str(prompts.PAGE_SIZE + 3)]))

    assert prompts.choose("Garment", rows) == rows[prompts.PAGE_SIZE + 2]
    out = capsys.readouterr().out
    assert "page 1/2" in out
    assert "page 2/2" in out
    assert f"row {prompts.PAGE_SIZE + 1}" in out


def test_paging_back_from_the_first_page_wraps_to_the_last(monkeypatch, capsys) -> None:
    monkeypatch.setattr(prompts, "fzf_command", lambda: None)
    monkeypatch.setattr(prompts, "prompt_toolkit_works", lambda: False)
    rows = [f"row {n}" for n in range(1, prompts.PAGE_SIZE * 2 + 1)]
    monkeypatch.setattr("builtins.input", _replies(["p", "1"]))

    assert prompts.choose("Garment", rows) == "row 1"
    assert "page 2/2" in capsys.readouterr().out


def test_n_is_not_a_page_command_when_everything_fits_on_one_page(monkeypatch, capsys) -> None:
    monkeypatch.setattr(prompts, "fzf_command", lambda: None)
    monkeypatch.setattr(prompts, "prompt_toolkit_works", lambda: False)
    monkeypatch.setattr("builtins.input", _replies(["n", "1"]))
    assert prompts.choose("Garment", ["one", "two"]) == "one"
    out = capsys.readouterr().out
    assert "not a number" in out
    assert "page" not in out


def test_a_blank_answer_cancels(monkeypatch) -> None:
    monkeypatch.setattr(prompts, "fzf_command", lambda: None)
    monkeypatch.setattr(prompts, "prompt_toolkit_works", lambda: False)
    monkeypatch.setattr("builtins.input", _replies([""]))
    assert prompts.choose("Garment", ["one"]) is None


def test_ctrl_c_cancels_rather_than_escaping(monkeypatch) -> None:
    monkeypatch.setattr(prompts, "fzf_command", lambda: None)
    monkeypatch.setattr(prompts, "prompt_toolkit_works", lambda: False)

    def interrupt(_: str) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupt)
    assert prompts.choose("Garment", ["one"]) is None


def test_choosing_from_an_empty_list_is_none_not_a_crash() -> None:
    assert prompts.choose("Garment", []) is None


def test_plain_text_and_confirm_fall_back_to_input(monkeypatch) -> None:
    monkeypatch.setattr(prompts, "prompt_toolkit_works", lambda: False)

    monkeypatch.setattr("builtins.input", _replies([""]))
    assert prompts.text("Template:", default="flat-lay-01") == "flat-lay-01"

    monkeypatch.setattr("builtins.input", _replies(["yes"]))
    assert prompts.confirm("Sure?", default=False) is True

    monkeypatch.setattr("builtins.input", _replies([""]))
    assert prompts.confirm("Sure?", default=True) is True


def test_plain_prompts_treat_eof_as_cancellation(monkeypatch) -> None:
    monkeypatch.setattr(prompts, "prompt_toolkit_works", lambda: False)

    def eof(_: str) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert prompts.text("Template:") is None
    assert prompts.confirm("Sure?") is None


# --- the marker glyph --------------------------------------------------------


def test_the_marker_falls_back_to_ascii_on_a_terminal_that_cannot_print_it() -> None:
    assert terminal.choose(LOCAL_MARKER, LOCAL_MARKER_FALLBACK, stream=_Stream("cp1252")) == (
        LOCAL_MARKER_FALLBACK
    )
    assert terminal.choose(LOCAL_MARKER, LOCAL_MARKER_FALLBACK, stream=_Stream("utf-8")) == (
        LOCAL_MARKER
    )


def test_both_marker_forms_occupy_the_same_width() -> None:
    """The emoji is East Asian Wide, so it is two terminal columns -- matching
    the two-character ASCII fallback keeps the brand column aligned either
    way."""
    assert len(LOCAL_MARKER_FALLBACK) == 2
    assert len(LOCAL_MARKER) == 1


def test_an_unknown_encoding_is_treated_as_unable_to_print() -> None:
    assert terminal.encodable("x", stream=_Stream("not-a-real-codec")) is False


# --- believing the shell about its encoding ----------------------------------
#
# Why the marker was showing as `* ` on a terminal that renders ⭐ perfectly:
# native-Windows Python takes its output encoding from the console codepage
# (cp1252), and a cygwin pty is a named pipe with no console behind it, so
# that answer describes nothing. mintty is UTF-8 and says so in LANG.


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({"LANG": "en_GB.UTF-8"}, True),
        ({"LANG": "en_GB.utf8"}, True),
        ({"LANG": "C"}, False),
        ({}, False),
        # LC_ALL outranks LC_CTYPE outranks LANG, and the first one that is
        # set decides outright rather than falling through to the next.
        ({"LC_ALL": "C", "LANG": "en_GB.UTF-8"}, False),
        ({"LC_CTYPE": "en_GB.UTF-8", "LANG": "C"}, True),
        ({"LC_ALL": "", "LANG": "en_GB.UTF-8"}, True),
    ],
)
def test_declared_utf8_reads_the_locale_the_shell_set(environ, expected: bool) -> None:
    assert terminal.declared_utf8(environ) is expected


def test_a_utf8_locale_re_encodes_the_output_streams(monkeypatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(terminal.sys, "stdout", _Reconfigurable(seen))
    monkeypatch.setattr(terminal.sys, "stderr", _Reconfigurable(seen))

    terminal.adopt_declared_encoding({"LANG": "en_GB.UTF-8"})

    assert seen == ["utf-8", "utf-8"]


def test_a_non_utf8_locale_leaves_the_streams_alone(monkeypatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(terminal.sys, "stdout", _Reconfigurable(seen))
    monkeypatch.setattr(terminal.sys, "stderr", _Reconfigurable(seen))

    terminal.adopt_declared_encoding({"LANG": "C"})

    assert seen == []


def test_an_explicit_pythonioencoding_wins(monkeypatch) -> None:
    """Someone naming an encoding on purpose is exactly what this must not
    second-guess."""
    seen: list[str] = []
    monkeypatch.setattr(terminal.sys, "stdout", _Reconfigurable(seen))
    monkeypatch.setattr(terminal.sys, "stderr", _Reconfigurable(seen))

    terminal.adopt_declared_encoding({"LANG": "en_GB.UTF-8", "PYTHONIOENCODING": "cp1252"})

    assert seen == []


def test_a_stream_that_cannot_be_reconfigured_is_skipped(monkeypatch) -> None:
    """pytest's own capture, a StringIO, a pipe wrapper: no `reconfigure`, and
    a decoration is never worth an AttributeError over."""
    seen: list[str] = []
    monkeypatch.setattr(terminal.sys, "stdout", _Stream("cp1252"))
    monkeypatch.setattr(terminal.sys, "stderr", _Reconfigurable(seen))

    terminal.adopt_declared_encoding({"LANG": "en_GB.UTF-8"})

    assert seen == ["utf-8"]


def test_a_stream_that_refuses_to_be_reconfigured_is_survived(monkeypatch) -> None:
    monkeypatch.setattr(terminal.sys, "stdout", _Reconfigurable(None))
    monkeypatch.setattr(terminal.sys, "stderr", _Reconfigurable(None))
    terminal.adopt_declared_encoding({"LANG": "en_GB.UTF-8"})  # does not raise


class _Stream:
    def __init__(self, encoding: str) -> None:
        self.encoding = encoding


class _Reconfigurable:
    """A stdout stand-in. ``seen is None`` means reconfiguring fails, which is
    what a stream wrapping a closed handle does."""

    encoding = "cp1252"

    def __init__(self, seen: list[str] | None) -> None:
        self._seen = seen

    def reconfigure(self, *, encoding: str) -> None:
        if self._seen is None:
            raise ValueError("cannot reconfigure")
        self._seen.append(encoding)


def _replies(answers: list[str]):
    queue = list(answers)

    def reply(_: str = "") -> str:
        return queue.pop(0)

    return reply


# --- the whole flow, on the backend cygwin actually gets ---------------------


def _one_garment_catalog():
    """One blueprint, one provider, one colour in two sizes -- enough to walk
    `new` end to end without a network. Carries an (empty) shipping fixture too
    -- the pricing-plan picker's "create new" flow always calls
    `catalog.shipping()`, and the fake raises on an unfixtured key rather than
    degrading, unlike the real fail-soft cost/FX fetches."""
    from etsy_listings.clients.printify.fakes import FakeCatalogClient
    from etsy_listings.clients.printify.models import (
        PrintAreaPlaceholder,
        PrintProvider,
        ShippingCost,
        ShippingProfile,
        ShippingRates,
        Variant,
        VariantOptions,
        VariantSet,
    )

    front = (PrintAreaPlaceholder(position="front", width=4500, height=5400),)
    return FakeCatalogClient(
        [GILDAN_TEE],
        {GILDAN_TEE.id: [PrintProvider(id=29, title="Monster Digital")]},
        {
            (GILDAN_TEE.id, 29): VariantSet(
                variants=(
                    Variant(
                        id=1,
                        title="Black / S",
                        options=VariantOptions(color="Black", size="S"),
                        placeholders=front,
                    ),
                    Variant(
                        id=2,
                        title="Black / M",
                        options=VariantOptions(color="Black", size="M"),
                        placeholders=front,
                    ),
                ),
            )
        },
        {
            (GILDAN_TEE.id, 29): ShippingRates(
                profiles=(
                    ShippingProfile(
                        variant_ids=(1, 2),
                        first_item=ShippingCost(currency="USD", cost=500),
                        additional_items=ShippingCost(currency="USD", cost=200),
                    ),
                )
            )
        },
    )


def _no_network_pricing_plan_generation(monkeypatch) -> None:
    """The "create new pricing plan" flow always calls the undocumented cost
    endpoint and a live FX API -- neither may run in a test. Both are
    fail-soft by design, so stubbing them to "no data" still produces a
    usable (all-zero-price) plan, matching the flow's own guarantees."""
    from etsy_listings.newcmd import fx_rate, unofficial_variant_costs

    monkeypatch.setattr(unofficial_variant_costs, "fetch_variant_costs", lambda *a, **k: {})
    monkeypatch.setattr(fx_rate, "fetch_usd_to", lambda *a, **k: None)


NEW_WIZARD: dict[str, object] = {
    "Garment": "Gildan",
    "Print provider": "Monster Digital",
    "Mockup template set": "flat-lay-01",
    "different artwork for light vs dark": False,
    "Pricing plan": "create a new",
    "Pricing plan name": "launch-low",
}
"""Answers to every question `new` asks on its main path, keyed by what it
asked rather than by when.

Not listed, because neither is on that path: `Design`, asked only when no
design name was given, and the per-colour `light or dark garment?`, asked only
after answering yes above. A test that wants either adds its own key.

The two pricing keys look ambiguous and are not: a fragment that is the whole
question wins outright, and otherwise the longest match does, so "Pricing plan
name:" takes the second and the bare "Pricing plan" picker takes the first.
See ``tests/support/scripted.py``.
"""


def _ordinal(rows: list[str], wanted: str) -> str:
    """``wanted``'s answer in the plain-input backend: its 1-based position.

    Derived rather than written down. A literal ``"2"`` means `flat-lay-01`
    only while it happens to be second in the fixture workspace's template
    list; add a template and every later reply shifts by one, so the run
    answers questions it was never meant to and fails somewhere that has
    nothing to do with the cause.
    """
    return str(rows.index(wanted) + 1)


def test_new_runs_end_to_end_through_the_plain_input_backend(
    workspace_root: Path, monkeypatch
) -> None:
    """The one test that drives `new` through a prompt *backend*.

    Everything below answers `prompts.choose`/`text`/`confirm` directly, which
    is the seam for what `new` decides and writes. This one goes the whole way
    down: no fzf, no prompt_toolkit, so every question is a numbered list read
    off `input()` -- the path every cygwin session takes, and the reason the
    fallback exists at all. Answers are positions here because positions are
    genuinely that backend's interface.
    """
    from etsy_listings.newcmd.interactive import run_new

    monkeypatch.setattr(prompts, "fzf_command", lambda: None)
    monkeypatch.setattr(prompts, "prompt_toolkit_works", lambda: False)
    _no_network_pricing_plan_generation(monkeypatch)

    workspace = Workspace.discover(root_override=workspace_root)
    monkeypatch.setattr(
        "builtins.input",
        _replies(
            [
                "1",  # Garment -- the fake catalog offers exactly one
                "1",  # Print provider -- likewise
                _ordinal(workspace.template_names(), "flat-lay-01"),
                "",  # no light/dark artwork split; blank takes the default
                "1",  # Pricing plan -- none on disk, so row 1 is "create a new"
                "launch-low",  # ...and its name
            ]
        ),
    )

    run_new(workspace, _one_garment_catalog(), "brand-new-design", "tshirt")

    listing = workspace_root / "listings" / "brand-new-design" / "listing.yaml"
    assert listing.is_file()
    assert "flat-lay-01" in listing.read_text(encoding="utf-8")
    assert (workspace_root / "profiles" / "gildan-5000.yaml").is_file()
    assert (workspace_root / "pricing-plans" / "launch-low.yaml").is_file()


def test_new_writes_a_listing_that_validates_against_a_single_kind_template(
    workspace_root: Path, monkeypatch, scripted
) -> None:
    """A `single`-kind template has one output and no colour to name (PRD 28).
    `new` used to write one `{template, colour}` entry per colour regardless of
    kind, which is not a listing the renderer accepts."""
    from etsy_listings.config.listing import Listing
    from etsy_listings.newcmd.interactive import run_new

    _no_network_pricing_plan_generation(monkeypatch)
    _write_single_kind_template(workspace_root / "mockup-templates" / "lifestyle-01")
    scripted(
        {
            **NEW_WIZARD,
            "Mockup template set": "lifestyle-01",
            "Pricing plan name": "single-kind-plan",
        }
    )

    workspace = Workspace.discover(root_override=workspace_root)
    run_new(workspace, _one_garment_catalog(), "single-kind-design", "tshirt")

    listing = Listing.load(
        workspace_root / "listings" / "single-kind-design" / "listing.yaml", currency="NOK"
    )
    assert len(listing.media) == 1
    assert listing.media[0].template == "lifestyle-01"
    assert listing.media[0].colour is None


def test_new_can_generate_a_pricing_plan_from_fabricated_cost_data(
    workspace_root: Path, monkeypatch, scripted
) -> None:
    """The "create new pricing plan" flow end to end, with the two live
    fetches stubbed to deterministic (non-empty) data instead of the
    all-zero fail-soft path -- confirms the generated file and the listing's
    `pricing_plan:` ref actually agree, and that a real price shows up."""
    from datetime import UTC, datetime
    from decimal import Decimal

    from etsy_listings.config.listing import Listing
    from etsy_listings.config.money import Money
    from etsy_listings.newcmd import fx_rate, unofficial_variant_costs
    from etsy_listings.newcmd.fx_rate import FxRate
    from etsy_listings.newcmd.interactive import run_new

    monkeypatch.setattr(
        unofficial_variant_costs, "fetch_variant_costs", lambda *a, **k: {1: 1000, 2: 1000}
    )
    fixed_rate = FxRate(rate=Decimal("10"), source="test", fetched_at=datetime.now(UTC))
    monkeypatch.setattr(fx_rate, "fetch_usd_to", lambda *a, **k: fixed_rate)
    scripted({**NEW_WIZARD, "Pricing plan name": "computed-plan"})

    catalog = _one_garment_catalog()
    workspace = Workspace.discover(root_override=workspace_root)
    run_new(workspace, catalog, "priced-design", "tshirt")

    plan_path = workspace_root / "pricing-plans" / "computed-plan.yaml"
    assert plan_path.is_file()
    plan = workspace.load_pricing_plan(plan_path)
    assert plan.profile == "gildan-5000"
    zero = Money.parse(f"0 {workspace.defaults.currency}")
    assert all(price != zero for price in plan.prices.values())  # real cost data was used

    listing = Listing.load(
        workspace_root / "listings" / "priced-design" / "listing.yaml", currency="NOK"
    )
    assert listing.pricing_plan == "../../pricing-plans/computed-plan.yaml"


def test_new_offers_an_existing_compatible_pricing_plan(
    workspace_root: Path, monkeypatch, scripted
) -> None:
    """A plan already on disk for this garment profile is picked straight
    from the list -- the wizard only needs to create one when none exist."""
    from etsy_listings.config.listing import Listing
    from etsy_listings.newcmd.interactive import run_new

    _no_network_pricing_plan_generation(monkeypatch)

    plans_dir = workspace_root / "pricing-plans"
    plans_dir.mkdir()
    (plans_dir / "existing.yaml").write_text(
        "profile: gildan-5000\nprices:\n  S: 100 NOK\n  M: 100 NOK\n",
        encoding="utf-8",
    )
    script = scripted({**NEW_WIZARD, "Pricing plan": "existing"})

    workspace = Workspace.discover(root_override=workspace_root)
    run_new(workspace, _one_garment_catalog(), "reuses-a-plan", "tshirt")

    listing = Listing.load(
        workspace_root / "listings" / "reuses-a-plan" / "listing.yaml", currency="NOK"
    )
    assert listing.pricing_plan == "../../pricing-plans/existing.yaml"
    assert not (plans_dir / "reuses-a-plan.yaml").exists()  # nothing new was written
    # It was offered as a *compatible* plan, marked and sorted above the
    # create-new row -- which is what makes reusing it the obvious answer.
    assert script.rows_for("Pricing plan")[0].endswith("existing")
    assert "Pricing plan name:" not in script.asked, "it never reached the create-new branch"


def test_cancelling_the_pricing_plan_picker_stops_new(
    workspace_root: Path, monkeypatch, scripted
) -> None:
    from etsy_listings.newcmd.interactive import run_new

    scripted({**NEW_WIZARD, "Pricing plan": None})

    workspace = Workspace.discover(root_override=workspace_root)
    with pytest.raises(prompts.Cancelled):
        run_new(workspace, _one_garment_catalog(), "cancelled-at-pricing", "tshirt")

    assert not (workspace_root / "listings" / "cancelled-at-pricing").exists()


SINGLE_KIND_TEMPLATE = """\
kind: single
colour: white
artwork: on-light
bounding_box:
- {x: 10.0, y: 10.0}
- {x: 90.0, y: 10.0}
- {x: 90.0, y: 90.0}
- {x: 10.0, y: 90.0}
"""


def _write_single_kind_template(directory: Path) -> None:
    directory.mkdir(parents=True)
    (directory / "template.yaml").write_text(SINGLE_KIND_TEMPLATE, encoding="utf-8")


def test_cancelling_the_garment_picker_stops_new(workspace_root: Path, scripted) -> None:
    from etsy_listings.clients.printify.fakes import FakeCatalogClient
    from etsy_listings.newcmd.interactive import run_new

    scripted({**NEW_WIZARD, "Garment": None})

    workspace = Workspace.discover(root_override=workspace_root)
    with pytest.raises(prompts.Cancelled):
        run_new(workspace, FakeCatalogClient([GILDAN_TEE], {}, {}), "another-design", "tshirt")

    assert not (workspace_root / "listings" / "another-design").exists()
