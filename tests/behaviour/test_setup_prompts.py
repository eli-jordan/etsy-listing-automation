"""`setup` and the workspace's AI prompts (market-seo.md, *Prompts and
`setup --replace-prompts`*; PRD 71's exception to "setup never overwrites").

Three packaged prompts, three outcomes each: a missing prompt is seeded; an
existing one is kept byte for byte, with a warning when it differs from its
packaged default; and under ``--replace-prompts`` a differing one is replaced,
the old file kept as ``<name>.md.bak``.

Driven through `run_setup` with the same doubles `test_setup_command.py`
uses, since the prompts are one step of the whole wizard; the flag's CLI
spelling gets one test through the Typer app.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from etsy_listings.ai.brief import default_brief_prompt_text
from etsy_listings.ai.market_queries import default_market_queries_prompt_text
from etsy_listings.ai.prompt import default_seo_prompt_text
from etsy_listings.cli.app import app
from etsy_listings.clients.printify.fakes import FakePrintifyClient
from etsy_listings.clients.printify.models import Shop
from etsy_listings.config.secrets import PRINTIFY_TOKEN_VAR
from etsy_listings.setupcmd.interactive import run_setup
from etsy_listings.workspace import layout
from etsy_listings.workspace.workspace import Workspace

HAPPY_PATH = {
    "token": "printify-token-abc",
    "currency": "NOK",
    "print provider": "",
    "print-on-demand defaults": True,
    "shipping profile": "",
    "production partner": "",
}

DEFAULTS = {
    layout.SEO_PROMPT_FILE: default_seo_prompt_text(),
    layout.BRIEF_PROMPT_FILE: default_brief_prompt_text(),
    layout.MARKET_QUERIES_PROMPT_FILE: default_market_queries_prompt_text(),
}


@pytest.fixture(autouse=True)
def _no_ambient_token(monkeypatch) -> None:
    monkeypatch.delenv(PRINTIFY_TOKEN_VAR, raising=False)


def _setup(root: Path, scripted, *, replace_prompts: bool = False) -> None:
    scripted(HAPPY_PATH)
    run_setup(
        root,
        client_factory=lambda _token: FakePrintifyClient([Shop(id=1, title="Store")]),
        etsy_access=lambda _root: None,
        replace_prompts=replace_prompts,
    )


def _prompt(root: Path, name: str) -> Path:
    return root / layout.PROMPTS_DIR / name


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _warnings(output: str) -> list[str]:
    return [line.strip() for line in output.splitlines() if line.strip().startswith("warning:")]


# ------------------------------------------------------------ seeding


def test_a_fresh_workspace_gets_all_three_packaged_prompts(tmp_path: Path, scripted) -> None:
    _setup(tmp_path, scripted)

    for name, text in DEFAULTS.items():
        assert _prompt(tmp_path, name).read_text(encoding="utf-8") == text
    assert not list((tmp_path / layout.PROMPTS_DIR).glob("*.bak"))


def test_the_queries_prompt_is_where_the_workspace_says_it_is(tmp_path: Path, scripted) -> None:
    _setup(tmp_path, scripted)

    workspace = Workspace.discover(root_override=tmp_path)
    assert workspace.market_queries_prompt_file() == _prompt(
        tmp_path, layout.MARKET_QUERIES_PROMPT_FILE
    )
    assert workspace.market_queries_prompt_file().is_file()


def test_a_re_run_over_the_packaged_prompts_warns_about_nothing(
    tmp_path: Path, scripted, capsys
) -> None:
    _setup(tmp_path, scripted)
    capsys.readouterr()

    _setup(tmp_path, scripted)

    assert _warnings(capsys.readouterr().out) == []


# ------------------------------------------------------------ without the flag


def test_an_existing_workspace_keeps_every_prompt_byte_for_byte(
    tmp_path: Path, scripted, capsys
) -> None:
    """The plan's success condition: prompts kept exactly, and one warning
    per prompt that differs -- naming the file and the flag."""
    edited = {
        layout.SEO_PROMPT_FILE: b"My own house style.\r\nNo trailing newline",
        layout.BRIEF_PROMPT_FILE: "Brief, café style.\n".encode(),
    }
    for name, data in edited.items():
        _write(_prompt(tmp_path, name), data)

    _setup(tmp_path, scripted)

    for name, data in edited.items():
        assert _prompt(tmp_path, name).read_bytes() == data
    assert not list((tmp_path / layout.PROMPTS_DIR).glob("*.bak"))
    warnings = _warnings(capsys.readouterr().out)
    assert warnings == [
        f"warning: {layout.PROMPTS_DIR}/{name} differs from the packaged default; "
        f"`etsy-listings setup --replace-prompts` replaces it and keeps yours as "
        f"{layout.PROMPTS_DIR}/{name}.bak"
        for name in (layout.SEO_PROMPT_FILE, layout.BRIEF_PROMPT_FILE)
    ]


def test_a_prompt_saved_with_windows_line_endings_is_not_a_difference(
    tmp_path: Path, scripted, capsys
) -> None:
    """An editor on Windows rewrites every line ending; the instructions are
    the same, and a warning about them would teach the seller to ignore it."""
    for name, text in DEFAULTS.items():
        _write(_prompt(tmp_path, name), text.replace("\n", "\r\n").encode())

    _setup(tmp_path, scripted)

    assert _warnings(capsys.readouterr().out) == []


# ------------------------------------------------------------ --replace-prompts


def test_replacing_keeps_the_old_prompt_as_a_bak(tmp_path: Path, scripted) -> None:
    old = b"My own house style.\r\n"
    _write(_prompt(tmp_path, layout.SEO_PROMPT_FILE), old)

    _setup(tmp_path, scripted, replace_prompts=True)

    seo = _prompt(tmp_path, layout.SEO_PROMPT_FILE)
    assert seo.read_text(encoding="utf-8") == DEFAULTS[layout.SEO_PROMPT_FILE]
    assert seo.with_name("seo.md.bak").read_bytes() == old


def test_replacing_overwrites_an_older_bak(tmp_path: Path, scripted) -> None:
    _write(_prompt(tmp_path, "seo.md.bak"), b"the edit before last")
    _write(_prompt(tmp_path, layout.SEO_PROMPT_FILE), b"the last edit")

    _setup(tmp_path, scripted, replace_prompts=True)

    assert _prompt(tmp_path, "seo.md.bak").read_bytes() == b"the last edit"


def test_replacing_seeds_a_missing_prompt_and_leaves_a_current_one_alone(
    tmp_path: Path, scripted, capsys
) -> None:
    """A prompt already equal to its default has nothing to back up, and
    writing a `.bak` for it would overwrite the one that holds the seller's
    last real edit."""
    _write(_prompt(tmp_path, "brief.md.bak"), b"an edit worth keeping")
    _write(_prompt(tmp_path, layout.BRIEF_PROMPT_FILE), DEFAULTS[layout.BRIEF_PROMPT_FILE].encode())

    _setup(tmp_path, scripted, replace_prompts=True)

    assert _prompt(tmp_path, "brief.md.bak").read_bytes() == b"an edit worth keeping"
    for name, text in DEFAULTS.items():
        assert _prompt(tmp_path, name).read_text(encoding="utf-8") == text
    assert _warnings(capsys.readouterr().out) == []


def test_replacing_says_what_it_replaced(tmp_path: Path, scripted, capsys) -> None:
    _write(_prompt(tmp_path, layout.SEO_PROMPT_FILE), b"mine")

    _setup(tmp_path, scripted, replace_prompts=True)

    out = capsys.readouterr().out
    assert (
        f"replaced {layout.PROMPTS_DIR}/seo.md with the default AI SEO prompt; "
        f"yours is {layout.PROMPTS_DIR}/seo.md.bak"
    ) in out


def test_replacing_leaves_a_prompt_setup_does_not_ship_alone(tmp_path: Path, scripted) -> None:
    _write(_prompt(tmp_path, "house-notes.md"), b"not a packaged prompt")

    _setup(tmp_path, scripted, replace_prompts=True)

    assert _prompt(tmp_path, "house-notes.md").read_bytes() == b"not a packaged prompt"
    assert not _prompt(tmp_path, "house-notes.md.bak").exists()


# ------------------------------------------------------------ the CLI flag


def test_the_cli_flag_reaches_setup(tmp_path: Path, monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_run_setup(root: Path, *, replace_prompts: bool = False) -> None:
        seen.update(root=root, replace_prompts=replace_prompts)

    monkeypatch.setattr("etsy_listings.setupcmd.run_setup", fake_run_setup)

    result = CliRunner().invoke(app, ["setup", "--root", str(tmp_path), "--replace-prompts"])

    assert result.exit_code == 0, result.output
    assert seen == {"root": tmp_path, "replace_prompts": True}


def test_setup_help_documents_the_flag() -> None:
    result = CliRunner().invoke(app, ["setup", "--help"])

    assert "--replace-prompts" in result.output
    assert ".bak" in result.output
