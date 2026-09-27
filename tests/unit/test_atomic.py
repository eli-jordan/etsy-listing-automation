"""`write_bytes_atomic` (A37): the file is either the old bytes or the new,
never a half-written one, and a failed write leaves nothing beside it."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from etsy_listings.workspace.atomic import write_bytes_atomic


def test_it_creates_the_directory_and_the_file(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "template.yaml"

    write_bytes_atomic(path, b"first")

    assert path.read_bytes() == b"first"


def test_it_replaces_an_existing_file_leaving_no_temporary(tmp_path: Path) -> None:
    path = tmp_path / "template.yaml"
    path.write_bytes(b"old")

    write_bytes_atomic(path, b"new")

    assert path.read_bytes() == b"new"
    assert [p.name for p in tmp_path.iterdir()] == ["template.yaml"]


def test_a_failed_replace_keeps_the_old_file_and_removes_the_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "template.yaml"
    path.write_bytes(b"old")

    def fail(*_: object) -> None:
        raise OSError("no space left")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="no space"):
        write_bytes_atomic(path, b"new")

    assert path.read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["template.yaml"]
