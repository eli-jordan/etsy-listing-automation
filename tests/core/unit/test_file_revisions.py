"""A workspace file's content revision and the save that checks it.

Admin plan, *Settled requirements*: a read returns a hash of the file's exact
bytes; a save compares it under the same lock as read, change and atomic
replace, and a conflict never overwrites.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from etsy_listings.core.workspace.revisions import (
    RevisionConflict,
    content_revision,
    read_revisioned,
    replace_if_unchanged,
)


def test_a_revision_names_the_exact_bytes(tmp_path: Path) -> None:
    path = tmp_path / "shop.yaml"
    path.write_bytes(b"a: 1\n")
    data, revision = read_revisioned(path)

    assert data == b"a: 1\n"
    assert revision == content_revision(b"a: 1\n")
    # A comment-only or line-ending change is still a different file.
    assert content_revision(b"a: 1\r\n") != revision
    assert content_revision(b"a: 1  # c\n") != revision


def test_a_save_against_the_current_revision_replaces_the_file(tmp_path: Path) -> None:
    path = tmp_path / "shop.yaml"
    path.write_bytes(b"a: 1\n")
    _, revision = read_revisioned(path)

    saved = replace_if_unchanged(path, revision, lambda data: data.replace(b"1", b"2"))

    assert path.read_bytes() == b"a: 2\n"
    assert saved.written
    assert saved.revision == content_revision(b"a: 2\n")


def test_a_save_against_a_stale_revision_refuses_and_writes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "shop.yaml"
    path.write_bytes(b"a: 1\n")
    _, revision = read_revisioned(path)
    path.write_bytes(b"a: 1\n# the seller's comment\n")
    seen: list[bytes] = []

    with pytest.raises(RevisionConflict):
        replace_if_unchanged(path, revision, lambda data: seen.append(data) or b"a: 2\n")

    assert seen == [], "the change is never computed against a file it was not made for"
    assert path.read_bytes() == b"a: 1\n# the seller's comment\n"


def test_an_unchanged_result_leaves_the_file_alone(tmp_path: Path) -> None:
    path = tmp_path / "shop.yaml"
    path.write_bytes(b"a: 1\r\n")
    before = path.stat().st_mtime_ns
    _, revision = read_revisioned(path)

    saved = replace_if_unchanged(path, revision, lambda data: data)

    assert not saved.written
    assert saved.revision == revision
    assert path.stat().st_mtime_ns == before


def test_a_refused_change_writes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "shop.yaml"
    path.write_bytes(b"a: 1\n")
    _, revision = read_revisioned(path)

    def refuse(_: bytes) -> bytes:
        raise ValueError("invalid")

    with pytest.raises(ValueError, match="invalid"):
        replace_if_unchanged(path, revision, refuse)
    assert path.read_bytes() == b"a: 1\n"


def test_two_saves_from_one_revision_cannot_both_win(tmp_path: Path) -> None:
    """The check and the replace hold one lock: the second save sees the
    first one's file, not the one both started from."""
    path = tmp_path / "shop.yaml"
    path.write_bytes(b"n: 0\n")
    _, revision = read_revisioned(path)
    inside = threading.Event()
    release = threading.Event()
    outcomes: list[str] = []

    def slow(data: bytes) -> bytes:
        inside.set()
        release.wait(5)
        return b"n: 1\n"

    def first() -> None:
        replace_if_unchanged(path, revision, slow)
        outcomes.append("first")

    thread = threading.Thread(target=first)
    thread.start()
    assert inside.wait(5)

    def second() -> None:
        try:
            replace_if_unchanged(path, revision, lambda data: b"n: 2\n")
            outcomes.append("second")
        except RevisionConflict:
            outcomes.append("conflict")

    other = threading.Thread(target=second)
    other.start()
    release.set()
    thread.join(5)
    other.join(5)

    assert sorted(outcomes) == ["conflict", "first"]
    assert path.read_bytes() == b"n: 1\n"
