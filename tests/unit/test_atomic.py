"""`write_bytes_atomic`: the file is either the old bytes or the new,
never a half-written one, and a failed write leaves nothing beside it.
`read_bytes_retrying` is its reader: a read that lands while Windows is
replacing the file waits the replace out rather than seeing no file."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from etsy_listings.workspace.atomic import read_bytes_retrying, write_bytes_atomic

from tests.support.refusals import refuse_reads


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


def test_a_replace_refused_while_a_reader_has_the_file_open_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows refuses ``os.replace`` onto a file another thread has open for
    reading -- CPython opens without ``FILE_SHARE_DELETE`` -- with a bare
    ``PermissionError``. A batch record is read by every summary poll while
    the queue writes it, so a refusal that lasts as long as one read is
    waited out rather than raised."""
    path = tmp_path / "batch.json"
    path.write_bytes(b"old")
    real = os.replace
    refusals = iter([PermissionError(13, "Access is denied")] * 2)

    def busy(source: str, target: Path) -> None:
        refusal = next(refusals, None)
        if refusal is not None:
            raise refusal
        real(source, target)

    monkeypatch.setattr(os, "replace", busy)
    monkeypatch.setattr("etsy_listings.workspace.atomic.time.sleep", lambda _: None)

    write_bytes_atomic(path, b"new")

    assert path.read_bytes() == b"new"
    assert [p.name for p in tmp_path.iterdir()] == ["batch.json"]


def test_a_replace_that_stays_refused_is_raised_and_leaves_no_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "batch.json"
    path.write_bytes(b"old")

    def refused(*_: object) -> None:
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(os, "replace", refused)
    monkeypatch.setattr("etsy_listings.workspace.atomic.time.sleep", lambda _: None)

    with pytest.raises(PermissionError):
        write_bytes_atomic(path, b"new")

    assert path.read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["batch.json"]


def test_a_read_refused_while_the_file_is_being_replaced_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "batch.json"
    path.write_bytes(b"record")
    refuse_reads(monkeypatch, 2)

    assert read_bytes_retrying(path) == b"record"


def test_a_missing_file_is_missing_at_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = refuse_reads(monkeypatch, 0)

    with pytest.raises(FileNotFoundError):
        read_bytes_retrying(tmp_path / "batch.json")

    assert sleeps == []


def test_a_read_that_stays_refused_is_raised_after_about_a_second(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "batch.json"
    path.write_bytes(b"record")
    sleeps = refuse_reads(monkeypatch, 1000)

    with pytest.raises(PermissionError):
        read_bytes_retrying(path)

    assert 0.5 <= sum(sleeps) <= 2
