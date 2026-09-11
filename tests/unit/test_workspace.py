from __future__ import annotations

import os
from pathlib import Path

import pytest

from etsy_listings.workspace.workspace import (
    AmbiguousColourSuffixError,
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
    assert (
        ws.garment_profile_file("comfort-colors-1717")
        == root / "garment-profiles" / "comfort-colors-1717.yaml"
    )
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


def test_a_templates_photos_are_everything_but_the_scene(workspace_root: Path) -> None:
    """What a colour-matrix set offers, read off its filenames -- PRD 7a makes
    the filename *be* the slugified colour, which is why this is a directory
    listing rather than a lookup table.

    Here rather than in the calibrator, which used to glob for it: the shape
    of a template directory is layout, and layout is this module's alone (A8).
    """
    ws = Workspace.discover(root_override=workspace_root)

    assert ws.template_colours("flat-lay-01") == ["black", "blue-jean", "ivory", "moss"]
    assert ws.template_colours("colour-chart-01") == []  # one photo, and it is the scene


def test_template_base_image_falls_back_to_a_trailing_segment_match(
    workspace_root: Path,
) -> None:
    """A vendor photo pack sharing one uninformative prefix across every file
    (PRD 7a) still resolves each colour, without renaming anything."""
    pack = workspace_root / "mockup-templates" / "vendor-pack"
    pack.mkdir()
    (pack / "comfort-colors-flat-lay-black.png").write_bytes(b"")
    (pack / "comfort-colors-flat-lay-blue-jean.png").write_bytes(b"")
    ws = Workspace.discover(root_override=workspace_root)

    assert ws.template_base_image("vendor-pack", "black") == (
        pack / "comfort-colors-flat-lay-black.png"
    )
    assert ws.template_base_image("vendor-pack", "blue-jean") == (
        pack / "comfort-colors-flat-lay-blue-jean.png"
    )


def test_template_base_image_prefers_an_exact_match_over_the_fallback(
    workspace_root: Path,
) -> None:
    pack = workspace_root / "mockup-templates" / "vendor-pack"
    pack.mkdir()
    (pack / "black.png").write_bytes(b"")
    (pack / "vendor-black.png").write_bytes(b"")
    ws = Workspace.discover(root_override=workspace_root)

    assert ws.template_base_image("vendor-pack", "black") == pack / "black.png"


def test_template_base_image_refuses_an_ambiguous_suffix_match(
    workspace_root: Path,
) -> None:
    pack = workspace_root / "mockup-templates" / "vendor-pack"
    pack.mkdir()
    (pack / "front-black.png").write_bytes(b"")
    (pack / "back-black.png").write_bytes(b"")
    ws = Workspace.discover(root_override=workspace_root)

    with pytest.raises(AmbiguousColourSuffixError):
        ws.template_base_image("vendor-pack", "black")


def test_template_base_image_with_no_match_at_all_answers_the_exact_path(
    workspace_root: Path,
) -> None:
    """Preserves the caller's own "no mockup base image" error (render.py's
    ``TemplateAssetError``) for a colour that truly has no photo."""
    ws = Workspace.discover(root_override=workspace_root)
    assert ws.template_base_image("flat-lay-01", "teal") == (
        ws.template_dir("flat-lay-01") / "teal.png"
    )


def test_the_preview_photo_prefers_the_scene_and_falls_back_to_a_colour(
    workspace_root: Path,
) -> None:
    """Answered without reading the config, which is the point: the rail has
    to show a thumbnail for a directory nobody has assigned a kind to yet."""
    ws = Workspace.discover(root_override=workspace_root)

    assert ws.template_preview_photo("colour-chart-01") == ws.template_scene_image(
        "colour-chart-01"
    )
    assert ws.template_preview_photo("flat-lay-01") == ws.template_base_image(
        "flat-lay-01", "black"
    )


def test_a_template_directory_that_is_not_there_answers_empty_not_raises(
    workspace_root: Path,
) -> None:
    """``has_template`` is the question with a yes/no answer; the accessors
    below it degrade, so a caller that skipped the check gets nothing rather
    than an exception about a directory."""
    ws = Workspace.discover(root_override=workspace_root)

    assert ws.has_template("flat-lay-01") is True
    assert ws.has_template("never-existed") is False
    assert ws.template_photos("never-existed") == []
    assert ws.template_colours("never-existed") == []
    assert ws.template_preview_photo("never-existed") is None


def test_test_design_names_lists_uploaded_targets_by_their_id(workspace_root: Path) -> None:
    """The id the library offers is the filename stem, which is what
    ``test_design_file`` resolves back -- so the two have to agree, and they
    agree by being written here together (A19)."""
    ws = Workspace.discover(root_override=workspace_root)
    assert ws.test_design_names() == []

    ws.test_designs_dir().mkdir(parents=True)
    ws.test_design_file("ink-weight").write_bytes(b"")

    assert ws.test_design_names() == ["ink-weight"]


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
    assert listing.prices["S"].currency == ws.defaults.etsy.currency


def test_workspace_loads_garment_profile_and_exceptions(workspace_root: Path) -> None:
    ws = Workspace.discover(root_override=workspace_root)
    blueprint = ws.load_garment_profile("comfort-colors-1717").blueprint
    assert (blueprint.brand, blueprint.model) == ("Comfort Colors", "1717")
    assert blueprint.title == "Unisex Garment-Dyed T-shirt"
    assert ws.load_exceptions().root == {}  # absent exceptions.yaml means "no exceptions"


# --- pricing plans: discovery (PRD 34) --------------------------------------


def test_pricing_plans_dir_is_a_workspace_top_level_directory(workspace_root: Path) -> None:
    ws = Workspace.discover(root_override=workspace_root)
    assert ws.pricing_plans_dir() == ws.root / "pricing-plans"


def test_pricing_plan_files_is_empty_without_a_pricing_plans_directory(
    workspace_root: Path,
) -> None:
    ws = Workspace.discover(root_override=workspace_root)
    assert ws.pricing_plan_files() == []


def test_pricing_plan_files_finds_flat_and_nested_files(workspace_root: Path) -> None:
    """Nested layouts are allowed here, unlike garment-profiles/mockup-templates --
    a plan's directory has no enforced meaning."""
    plans_dir = workspace_root / "pricing-plans"
    plans_dir.mkdir()
    (plans_dir / "launch-low.yaml").write_text("garment_profile: p\nprices: {}\n", encoding="utf-8")
    nested = plans_dir / "comfort-colors-1717"
    nested.mkdir()
    (nested / "premium.yaml").write_text("garment_profile: p\nprices: {}\n", encoding="utf-8")

    ws = Workspace.discover(root_override=workspace_root)
    found = ws.pricing_plan_files()

    assert found == sorted(found)
    assert plans_dir / "launch-low.yaml" in found
    assert nested / "premium.yaml" in found
    assert len(found) == 2


def test_load_pricing_plan_attaches_the_workspace_currency(workspace_root: Path) -> None:
    plans_dir = workspace_root / "pricing-plans"
    plans_dir.mkdir()
    path = plans_dir / "launch-low.yaml"
    path.write_text(
        "garment_profile: comfort-colors-1717\nprices:\n  S: 100 NOK\n", encoding="utf-8"
    )

    ws = Workspace.discover(root_override=workspace_root)
    plan = ws.load_pricing_plan(path)

    assert plan.garment_profile == "comfort-colors-1717"
    assert plan.prices["S"].currency == ws.defaults.etsy.currency
