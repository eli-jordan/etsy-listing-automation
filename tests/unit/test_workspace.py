from __future__ import annotations

import os
from pathlib import Path

import pytest

from etsy_listings.workspace.workspace import (
    InvalidNameError,
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


# --- layout accessors: the single place that knows the tree's shape ---


def test_layout_accessors_point_at_the_documented_locations(workspace_root: Path) -> None:
    ws = Workspace.discover(root_override=workspace_root)
    root = ws.root
    assert ws.listing_file("take-a-hike") == root / "listings" / "take-a-hike" / "listing.yaml"
    assert ws.lock_file("take-a-hike") == root / "listings" / "take-a-hike" / "state.lock.json"
    assert ws.profile_file("comfort-colors-1717") == root / "profiles" / "comfort-colors-1717.yaml"
    assert ws.exceptions_file() == root / "exceptions.yaml"
    assert ws.template_dir("flat-lay-01") == root / "mockup-templates" / "flat-lay-01"
    assert (
        ws.template_config_file("flat-lay-01") == ws.template_dir("flat-lay-01") / "template.yaml"
    )
    assert ws.template_derived_dir("flat-lay-01") == ws.template_dir("flat-lay-01") / "_derived"
    assert (
        ws.template_base_image("flat-lay-01", "black")
        == ws.template_dir("flat-lay-01") / "black.png"
    )
    assert (
        ws.template_scene_image("colour-chart-01")
        == ws.template_dir("colour-chart-01") / "scene.png"
    )
    assert ws.render_file("take-a-hike", "flat-lay-01", "black") == (
        root / ".cache" / "renders" / "take-a-hike" / "flat-lay-01" / "black.png"
    )
    assert ws.render_file("take-a-hike", "colour-chart-01") == (
        root / ".cache" / "renders" / "take-a-hike" / "colour-chart-01" / "scene.png"
    )
    assert ws.catalog_cache_dir() == root / ".cache" / "catalog"


def test_listing_names_finds_listings_with_a_listing_file(workspace_root: Path) -> None:
    ws = Workspace.discover(root_override=workspace_root)
    assert ws.listing_names() == ["take-a-hike"]


def test_listing_names_ignores_directories_without_a_listing_file(workspace_root: Path) -> None:
    (workspace_root / "listings" / "not-a-listing").mkdir()
    ws = Workspace.discover(root_override=workspace_root)
    assert ws.listing_names() == ["take-a-hike"]


def test_template_names_can_include_uncalibrated_directories(workspace_root: Path) -> None:
    """The calibrator is what writes template.yaml, so its UI has to see past
    the default filter -- otherwise a directory could never be selected in
    order to calibrate it. A stray file stays out either way.

    The default (calibrated-only) behaviour the `new` picker relies on is
    covered in tests/behaviour/test_new_picker.py.
    """
    templates = workspace_root / "mockup-templates"
    (templates / "not-calibrated-yet").mkdir()
    (templates / "stray.png").write_bytes(b"")
    ws = Workspace.discover(root_override=workspace_root)

    assert ws.template_names() == ["colour-chart-01", "flat-lay-01"]
    assert ws.template_names(include_uncalibrated=True) == [
        "colour-chart-01",
        "flat-lay-01",
        "not-calibrated-yet",
    ]


@pytest.mark.parametrize(
    "name",
    ["..", ".", "", "../escape", "nested/name", "back\\slash", "C:evil"],
)
def test_layout_accessors_reject_names_that_are_not_a_single_segment(
    workspace_root: Path, name: str
) -> None:
    """Names reach these accessors from config files and from URLs, so a
    traversal attempt must be refused before it is ever joined to the root."""
    ws = Workspace.discover(root_override=workspace_root)
    with pytest.raises(InvalidNameError):
        ws.template_dir(name)
    with pytest.raises(InvalidNameError):
        ws.listing_file(name)


def test_workspace_loads_listing_with_the_workspace_currency(workspace_root: Path) -> None:
    """The workspace owns shop.yaml, so callers never pass `currency=`
    themselves -- the one argument it was possible to get quietly wrong."""
    ws = Workspace.discover(root_override=workspace_root)
    listing = ws.load_listing("take-a-hike")
    assert listing.prices["S"].currency == ws.defaults.currency


def test_workspace_loads_profile_and_exceptions(workspace_root: Path) -> None:
    ws = Workspace.discover(root_override=workspace_root)
    assert ws.load_profile("comfort-colors-1717").blueprint == "Comfort Colors 1717"
    assert ws.load_exceptions().root == {}  # absent exceptions.yaml means "no exceptions"
