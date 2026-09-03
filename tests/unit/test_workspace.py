from __future__ import annotations

import os
from pathlib import Path

import pytest

from etsy_listings.workspace.workspace import (
    PathEscapesWorkspaceError,
    Workspace,
    WorkspaceNotFoundError,
)


def test_discover_finds_root_from_nested_cwd(workspace_root: Path) -> None:
    nested = workspace_root / "listings" / "take-a-hike"
    ws = Workspace.discover(start=nested)
    assert ws.root == workspace_root.resolve()


def test_discover_root_override_wins(workspace_root: Path, tmp_path: Path) -> None:
    ws = Workspace.discover(start=tmp_path, root_override=workspace_root)
    assert ws.root == workspace_root.resolve()


def test_discover_env_var(
    workspace_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ETSY_LISTINGS_ROOT", str(workspace_root))
    ws = Workspace.discover(start=tmp_path)
    assert ws.root == workspace_root.resolve()


def test_discover_raises_when_not_found(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceNotFoundError):
        Workspace.discover(start=tmp_path)


def test_resolve_within_root(workspace_root: Path) -> None:
    ws = Workspace.discover(root_override=workspace_root)
    listing_dir = ws.root / "listings" / "take-a-hike"
    resolved = ws.resolve("../../designs/take-a-hike.png", relative_to=listing_dir)
    assert resolved == (ws.root / "designs" / "take-a-hike.png").resolve()


def test_resolve_rejects_parent_escape(workspace_root: Path) -> None:
    ws = Workspace.discover(root_override=workspace_root)
    with pytest.raises(PathEscapesWorkspaceError):
        ws.resolve("../../../outside.png", relative_to=ws.root / "listings" / "take-a-hike")


def test_resolve_rejects_posix_absolute(workspace_root: Path) -> None:
    ws = Workspace.discover(root_override=workspace_root)
    with pytest.raises(PathEscapesWorkspaceError):
        ws.resolve("/etc/passwd", relative_to=ws.root)


def test_resolve_rejects_windows_drive_absolute(workspace_root: Path) -> None:
    ws = Workspace.discover(root_override=workspace_root)
    with pytest.raises(PathEscapesWorkspaceError):
        ws.resolve("C:\\Windows\\System32\\config", relative_to=ws.root)


def test_resolve_rejects_windows_drive_relative(workspace_root: Path) -> None:
    ws = Workspace.discover(root_override=workspace_root)
    with pytest.raises(PathEscapesWorkspaceError):
        ws.resolve("C:secrets.txt", relative_to=ws.root)


def test_resolve_rejects_unc_path(workspace_root: Path) -> None:
    ws = Workspace.discover(root_override=workspace_root)
    with pytest.raises(PathEscapesWorkspaceError):
        ws.resolve("\\\\server\\share\\file.txt", relative_to=ws.root)


@pytest.mark.skipif(os.name != "nt", reason="symlink escape test targets Windows path semantics")
def test_resolve_rejects_symlink_escape(workspace_root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.png").write_text("secret")
    link = workspace_root / "designs" / "escape-link"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("creating symlinks requires elevated privileges on this machine")

    ws = Workspace.discover(root_override=workspace_root)
    with pytest.raises(PathEscapesWorkspaceError):
        ws.resolve("escape-link/secret.png", relative_to=ws.root / "designs")


def test_cache_path_is_under_root(workspace_root: Path) -> None:
    ws = Workspace.discover(root_override=workspace_root)
    assert (
        ws.cache("catalog", "blueprints.json") == ws.root / ".cache" / "catalog" / "blueprints.json"
    )
