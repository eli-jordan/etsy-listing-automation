from __future__ import annotations

import os
from pathlib import Path

import pytest

from etsy_listings.workspace.userpath import to_native_path

windows_only = pytest.mark.skipif(os.name != "nt", reason="translation is a Windows-only concern")


@windows_only
@pytest.mark.parametrize(
    ("posix", "expected"),
    [
        ("/cygdrive/c/Users/Admin", r"C:\Users\Admin"),
        ("/cygdrive/d/data/designs", r"D:\data\designs"),
        ("/cygdrive/C/Users/Admin", r"C:\Users\Admin"),  # uppercase drive letter
        ("/cygdrive/c", "C:\\"),  # bare drive, no trailing path
    ],
)
def test_translates_cygdrive_paths_without_needing_cygwin(posix: str, expected: str) -> None:
    assert to_native_path(posix) == Path(expected)


@windows_only
def test_leaves_native_windows_paths_alone() -> None:
    assert to_native_path(r"C:\Users\Admin\workspace") == Path(r"C:\Users\Admin\workspace")


@windows_only
def test_leaves_relative_paths_alone() -> None:
    assert to_native_path("tests/fixtures/workspace") == Path("tests/fixtures/workspace")


@windows_only
def test_translates_cygwin_home_path_via_cygpath() -> None:
    """The case this module exists for: `--root /home/Admin/...` typed in a
    Cygwin shell. Only cygpath can resolve it (it needs the mount table), so
    this asserts the real translation when cygpath is available."""
    import shutil

    if shutil.which("cygpath") is None:
        pytest.skip("cygpath not on PATH; nothing to translate against")

    result = to_native_path("/home/Admin")
    assert result.drive  # became a real drive-anchored Windows path
    assert "/home" not in str(result)


@windows_only
def test_untranslatable_path_is_returned_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without cygpath there is no mount table to consult, so the original
    path is preserved -- a wrong guess would be worse than the plain error."""
    monkeypatch.setattr("etsy_listings.workspace.userpath.shutil.which", lambda _: None)
    assert to_native_path("/home/Admin/workspace") == Path("/home/Admin/workspace")


def test_is_a_no_op_on_posix_platforms(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("etsy_listings.workspace.userpath.os.name", "posix")
    assert to_native_path("/home/admin/workspace") == Path("/home/admin/workspace")
