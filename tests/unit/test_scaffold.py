"""The two files both `auth` and `setup` write into a workspace.

Moved here from `setup`'s tests when `auth` gained the same need (PRD 49) --
one subject per file, and this one is no longer `setup`'s. What matters about
both writers is the same thing: they edit a file the user also owns, so what
they leave alone is as much the behaviour as what they change.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.workspace import layout, scaffold

# -------------------------------------------------------------- .gitignore


def test_a_fresh_gitignore_gets_every_secret_path(tmp_path: Path) -> None:
    added = scaffold.update_gitignore(tmp_path)

    content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    for entry in (layout.ENV_FILE, layout.AUTH_DIR, layout.CACHE_DIR):
        assert entry in content
        assert any(entry in line for line in added)


def test_gitignore_only_appends_what_is_missing(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text(f"{layout.ENV_FILE}\nnotes.txt\n", encoding="utf-8")

    added = scaffold.update_gitignore(tmp_path)

    content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert content.count(layout.ENV_FILE) == 1
    assert "notes.txt" in content
    assert not any(line.strip() == layout.ENV_FILE for line in added)


def test_gitignore_is_left_alone_when_it_already_covers_everything(tmp_path: Path) -> None:
    scaffold.update_gitignore(tmp_path)
    before = (tmp_path / ".gitignore").read_text(encoding="utf-8")

    assert scaffold.update_gitignore(tmp_path) == ()
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == before


# --------------------------------------------------------------------- .env


@pytest.mark.parametrize(
    ("existing", "expected"),
    [
        ("", "PRINTIFY_API_TOKEN=abc\n"),
        ("OTHER=1\n", "OTHER=1\nPRINTIFY_API_TOKEN=abc\n"),
        ("PRINTIFY_API_TOKEN=old\n", "PRINTIFY_API_TOKEN=abc\n"),
        ("A=1\nPRINTIFY_API_TOKEN=old\nB=2\n", "A=1\nPRINTIFY_API_TOKEN=abc\nB=2\n"),
        ("OTHER=1", "OTHER=1\nPRINTIFY_API_TOKEN=abc\n"),
    ],
)
def test_setting_an_env_value_replaces_in_place_and_keeps_the_rest(
    existing: str, expected: str
) -> None:
    assert scaffold.env_with(existing, "PRINTIFY_API_TOKEN", "abc") == expected


def test_setting_an_env_value_leaves_comments_alone() -> None:
    existing = "# a note\nPRINTIFY_API_TOKEN=old\n"

    assert (
        scaffold.env_with(existing, "PRINTIFY_API_TOKEN", "abc")
        == "# a note\nPRINTIFY_API_TOKEN=abc\n"
    )


def test_a_commented_out_key_is_not_mistaken_for_the_real_one() -> None:
    existing = "#PRINTIFY_API_TOKEN=old\n"
    result = scaffold.env_with(existing, "PRINTIFY_API_TOKEN", "abc")

    assert result == "#PRINTIFY_API_TOKEN=old\nPRINTIFY_API_TOKEN=abc\n"


def test_writing_a_value_creates_the_env_file_and_returns_its_path(tmp_path: Path) -> None:
    path = scaffold.write_env_value(tmp_path, "ETSY_KEYSTRING", "abc123")

    assert path == tmp_path / layout.ENV_FILE
    assert path.read_text(encoding="utf-8") == "ETSY_KEYSTRING=abc123\n"


def test_writing_a_second_value_keeps_the_first(tmp_path: Path) -> None:
    scaffold.write_env_value(tmp_path, "ETSY_KEYSTRING", "abc123")
    scaffold.write_env_value(tmp_path, "ETSY_SHARED_SECRET", "s3cret")

    content = (tmp_path / layout.ENV_FILE).read_text(encoding="utf-8")
    assert content == "ETSY_KEYSTRING=abc123\nETSY_SHARED_SECRET=s3cret\n"
