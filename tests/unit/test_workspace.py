from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from etsy_listings.config.errors import ConfigLoadError
from etsy_listings.workspace.workspace import (
    AmbiguousColourSuffixError,
    InvalidNameError,
    InvalidRefError,
    PathEscapesWorkspaceError,
    Workspace,
    WorkspaceNotFoundError,
    remove_tree,
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
    resolved = ws.resolve("designs/take-a-hike.png", relative_to=ws.root)
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


class TestResolveRef:
    """PRD 72: every path in `listing.yaml` is a ref with two roots."""

    @pytest.fixture
    def ws(self, workspace_root: Path) -> Workspace:
        return Workspace.discover(root_override=workspace_root)

    def test_a_ref_with_no_prefix_is_the_workspace_root(self, ws: Workspace) -> None:
        listing_dir = ws.listing_dir("take-a-hike")
        resolved = ws.resolve_ref("designs/take-a-hike.png", listing_dir=listing_dir)
        assert resolved == ws.root / "designs" / "take-a-hike.png"

    def test_a_dot_slash_ref_is_the_listing_directory(self, ws: Workspace) -> None:
        listing_dir = ws.listing_dir("take-a-hike")
        resolved = ws.resolve_ref("./close-up.mp4", listing_dir=listing_dir)
        assert resolved == ws.root / "listings" / "take-a-hike" / "close-up.mp4"

    def test_subdirectories_are_allowed_under_either_root(self, ws: Workspace) -> None:
        listing_dir = ws.listing_dir("take-a-hike")
        assert (
            ws.resolve_ref("./shots/back.png", listing_dir=listing_dir)
            == ws.root / "listings" / "take-a-hike" / "shots" / "back.png"
        )
        assert (
            ws.resolve_ref("pricing-plans/tees/basic.yaml", listing_dir=listing_dir)
            == ws.root / "pricing-plans" / "tees" / "basic.yaml"
        )

    def test_a_legacy_parent_ref_names_the_migration_script(self, ws: Workspace) -> None:
        with pytest.raises(InvalidRefError, match=r"scripts/migrate_workspace_refs\.py"):
            ws.resolve_ref("../../designs/take-a-hike.png", listing_dir=ws.listing_dir("x"))

    @pytest.mark.parametrize(
        "ref",
        [
            "designs/../listings/x/secret.png",
            "./shots/../../other/listing.yaml",
            "common-media/..",
            "..",
        ],
    )
    def test_dot_dot_anywhere_is_refused(self, ws: Workspace, ref: str) -> None:
        with pytest.raises(InvalidRefError, match=r"'\.\.'"):
            ws.resolve_ref(ref, listing_dir=ws.listing_dir("x"))

    @pytest.mark.parametrize(
        "ref", ["/etc/passwd", "C:\\Windows\\x.png", "C:x.png", "//server/share/x.png"]
    )
    def test_an_absolute_ref_is_refused(self, ws: Workspace, ref: str) -> None:
        with pytest.raises(InvalidRefError, match="absolute"):
            ws.resolve_ref(ref, listing_dir=ws.listing_dir("x"))

    def test_a_backslash_is_refused(self, ws: Workspace) -> None:
        with pytest.raises(InvalidRefError, match="backslash"):
            ws.resolve_ref("designs\\take-a-hike.png", listing_dir=ws.listing_dir("x"))

    @pytest.mark.parametrize("ref", ["", "./", "."])
    def test_an_empty_ref_is_refused(self, ws: Workspace, ref: str) -> None:
        with pytest.raises(InvalidRefError, match="empty"):
            ws.resolve_ref(ref, listing_dir=ws.listing_dir("x"))

    def test_the_error_is_a_config_error_about_the_listing_file(self, ws: Workspace) -> None:
        listing_dir = ws.listing_dir("take-a-hike")
        with pytest.raises(ConfigLoadError) as caught:
            ws.resolve_ref("../x.png", listing_dir=listing_dir)
        assert caught.value.path == listing_dir / "listing.yaml"

    @pytest.mark.skipif(os.name == "nt", reason="symlinks need elevation on Windows")
    def test_it_still_refuses_a_symlink_out_of_the_root(
        self, ws: Workspace, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (ws.root / "designs" / "escape-link").symlink_to(outside)
        with pytest.raises(InvalidRefError, match="escapes"):
            ws.resolve_ref("designs/escape-link/secret.png", listing_dir=ws.listing_dir("x"))


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
    assert ws.seo_prompt_file() == root / "prompts" / "seo.md"
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
    assert ws.common_media_file("size-guide.png") == root / "common-media" / "size-guide.png"


def test_common_media_files_lists_every_image_and_video_recursively(
    workspace_root: Path,
) -> None:
    """The other half of `media:` -- a file ref to something shared across
    listings, rather than a rendered mockup. Every type `media:` accepts
    (PRD 71), in subdirectories too, sorted by path."""
    shared = workspace_root / "common-media"
    (shared / "videos").mkdir(parents=True)
    for name in ("size-guide.png", "care.JPG", "photo.jpeg", "videos/intro.mp4", "clip.MOV"):
        (shared / name).write_bytes(b"")
    (shared / "notes.txt").write_text("not media", encoding="utf-8")
    (shared / "videos" / "raw.webm").write_bytes(b"")

    ws = Workspace.discover(root_override=workspace_root)
    assert [p.relative_to(shared).as_posix() for p in ws.common_media_files()] == [
        "care.JPG",
        "clip.MOV",
        "photo.jpeg",
        "size-guide.png",
        "videos/intro.mp4",
    ]


def test_common_media_file_takes_the_path_under_common_media_as_is(
    workspace_root: Path,
) -> None:
    """No `.png` appended: a shared file may be a JPEG or a video, and may
    sit in a subdirectory, so the caller names it in full."""
    ws = Workspace.discover(root_override=workspace_root)
    assert ws.common_media_file("videos/intro.mp4") == (
        workspace_root / "common-media" / "videos" / "intro.mp4"
    )


@pytest.mark.parametrize(
    "name",
    ["../shop.yaml", "videos/../../shop.yaml", "", "a//b.png", "C:x.png", "a\\b.png", "notes.txt"],
)
def test_common_media_file_refuses_a_path_that_could_leave_common_media(
    workspace_root: Path, name: str
) -> None:
    """It takes names from URLs (A8): a security boundary."""
    ws = Workspace.discover(root_override=workspace_root)
    with pytest.raises(InvalidNameError):
        ws.common_media_file(name)


@pytest.mark.skipif(os.name == "nt", reason="symlinks need elevation on Windows")
def test_common_media_refuses_a_symlink_out_of_common_media(workspace_root: Path) -> None:
    """Inside the root is not enough: `shop.yaml` behind a `.png` name is not
    a shared picture, and neither listed nor served."""
    shared = workspace_root / "common-media"
    shared.mkdir()
    (shared / "shop.png").symlink_to(workspace_root / "shop.yaml")

    ws = Workspace.discover(root_override=workspace_root)
    assert ws.common_media_files() == []
    with pytest.raises(InvalidNameError):
        ws.common_media_file("shop.png")


def test_common_media_files_is_empty_when_the_directory_is_absent(workspace_root: Path) -> None:
    """A workspace that has never needed a shared asset still lists."""
    ws = Workspace.discover(root_override=workspace_root)
    assert ws.common_media_files() == []


class TestListingMediaFiles:
    """A listing's own files, the `./` half of `media:` (PRD 71, 72).

    A security boundary (A8): the listing name and the path both arrive from
    URLs, and the directory also holds `listing.yaml` and the lockfile, which
    are no business of a picture endpoint."""

    def test_lists_every_image_and_video_recursively_by_path(self, workspace_root: Path) -> None:
        listing = workspace_root / "listings" / "take-a-hike"
        (listing / "shots").mkdir()
        for name in ("close-up.MP4", "shots/back.png", "shots/detail.jpeg", "a.mov"):
            (listing / name).write_bytes(b"")
        (listing / "notes.txt").write_text("not media", encoding="utf-8")

        ws = Workspace.discover(root_override=workspace_root)
        assert [
            p.relative_to(listing).as_posix() for p in ws.listing_media_files("take-a-hike")
        ] == [
            "a.mov",
            "close-up.MP4",
            "shots/back.png",
            "shots/detail.jpeg",
        ]

    def test_never_lists_the_listing_file_or_the_lockfile(self, workspace_root: Path) -> None:
        listing = workspace_root / "listings" / "take-a-hike"
        (listing / "state.lock.json").write_text("{}", encoding="utf-8")

        ws = Workspace.discover(root_override=workspace_root)
        assert ws.listing_media_files("take-a-hike") == []

    def test_is_empty_for_a_listing_with_no_directory(self, workspace_root: Path) -> None:
        ws = Workspace.discover(root_override=workspace_root)
        assert ws.listing_media_files("no-such-listing") == []

    @pytest.mark.parametrize("name", ["..", "../take-a-hike", "", "a\\b"])
    def test_refuses_a_listing_name_that_is_not_one_segment(
        self, workspace_root: Path, name: str
    ) -> None:
        ws = Workspace.discover(root_override=workspace_root)
        with pytest.raises(InvalidNameError):
            ws.listing_media_files(name)

    @pytest.mark.skipif(os.name == "nt", reason="symlinks need elevation on Windows")
    def test_leaves_out_a_symlink_that_points_out_of_the_listing(
        self, workspace_root: Path
    ) -> None:
        """Inside the root is not enough: a link to another listing's files, or
        to `shop.yaml` behind a `.png` name, is outside this listing."""
        listing = workspace_root / "listings" / "take-a-hike"
        (listing / "shop.png").symlink_to(workspace_root / "shop.yaml")
        (listing / "design.png").symlink_to(workspace_root / "designs" / "take-a-hike.png")
        (listing / "self.png").symlink_to(listing / "listing.yaml")

        ws = Workspace.discover(root_override=workspace_root)
        assert ws.listing_media_files("take-a-hike") == []

    def test_resolves_one_file_by_its_path_under_the_listing(self, workspace_root: Path) -> None:
        listing = workspace_root / "listings" / "take-a-hike"
        (listing / "shots").mkdir()
        (listing / "shots" / "back.png").write_bytes(b"")

        ws = Workspace.discover(root_override=workspace_root)
        assert (
            ws.listing_media_file("take-a-hike", "shots/back.png") == listing / "shots" / "back.png"
        )

    @pytest.mark.parametrize(
        "path",
        [
            "listing.yaml",
            "state.lock.json",
            "../../shop.yaml",
            "shots/../../../shop.yaml",
            "../other/x.png",
            "",
            "a//b.png",
            "C:x.png",
            "a\\b.png",
            "notes.txt",
        ],
    )
    def test_refuses_a_path_that_is_not_one_of_its_media_files(
        self, workspace_root: Path, path: str
    ) -> None:
        ws = Workspace.discover(root_override=workspace_root)
        with pytest.raises(InvalidNameError):
            ws.listing_media_file("take-a-hike", path)

    @pytest.mark.skipif(os.name == "nt", reason="symlinks need elevation on Windows")
    def test_refuses_a_symlink_out_of_the_listing(self, workspace_root: Path) -> None:
        listing = workspace_root / "listings" / "take-a-hike"
        (listing / "shop.png").symlink_to(workspace_root / "shop.yaml")
        (listing / "design.png").symlink_to(workspace_root / "designs" / "take-a-hike.png")

        ws = Workspace.discover(root_override=workspace_root)
        for path in ("shop.png", "design.png"):
            with pytest.raises(InvalidNameError):
                ws.listing_media_file("take-a-hike", path)


def test_common_copy_files_lists_the_shared_bodies(workspace_root: Path) -> None:
    """The common-copy picker's source list (AI SEO implementation plan, PR6):
    every reusable description body, so the editor can offer one without a
    seller having to know or type its filename."""
    shared = workspace_root / "common-copy"
    shared.mkdir(exist_ok=True)
    (shared / "comfort-colors.md").write_text("---\ntitle: x\n---\nbody", encoding="utf-8")
    (shared / "care.md").write_text("---\ntitle: y\n---\nbody", encoding="utf-8")
    (shared / "notes.txt").write_text("not markdown", encoding="utf-8")

    ws = Workspace.discover(root_override=workspace_root)
    assert [p.name for p in ws.common_copy_files()] == ["care.md", "comfort-colors.md"]


def test_common_copy_files_is_empty_when_the_directory_is_absent(workspace_root: Path) -> None:
    ws = Workspace.discover(root_override=workspace_root)
    assert ws.common_copy_files() == []


def test_listing_names_finds_listings_with_a_listing_file(workspace_root: Path) -> None:
    ws = Workspace.discover(root_override=workspace_root)
    assert ws.listing_names() == ["take-a-hike"]


def test_listing_names_ignores_directories_without_a_listing_file(workspace_root: Path) -> None:
    (workspace_root / "listings" / "not-a-listing").mkdir()
    ws = Workspace.discover(root_override=workspace_root)
    assert ws.listing_names() == ["take-a-hike"]


def test_listing_names_includes_a_lockfile_only_directory(workspace_root: Path) -> None:
    """PRD 67: yaml gone, lockfile still there -- the row still appears."""
    orphan = workspace_root / "listings" / "orphan"
    orphan.mkdir()
    (orphan / "state.lock.json").write_text("{}", encoding="utf-8")
    ws = Workspace.discover(root_override=workspace_root)
    assert ws.listing_names() == ["orphan", "take-a-hike"]


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


def test_renders_dir_is_the_parent_of_every_render_for_that_listing(workspace_root: Path) -> None:
    """Renaming a listing has to move this, so it is an accessor rather than a
    path the rename endpoint spells for itself (A8)."""
    ws = Workspace.discover(root_override=workspace_root)
    assert ws.renders_dir("take-a-hike") == workspace_root / ".cache" / "renders" / "take-a-hike"
    assert ws.render_file("take-a-hike", "flat-lay-01", "black").parent.parent == ws.renders_dir(
        "take-a-hike"
    )


def test_renders_dir_refuses_a_name_that_is_not_a_path_segment(workspace_root: Path) -> None:
    ws = Workspace.discover(root_override=workspace_root)
    with pytest.raises(InvalidNameError):
        ws.renders_dir("../escape")


# --- preview accessors (A32) --------------------------------------------


def test_preview_dir_sits_beside_the_render_cache(workspace_root: Path) -> None:
    ws = Workspace.discover(root_override=workspace_root)
    assert ws.preview_dir("take-a-hike") == workspace_root / ".cache" / "previews" / "take-a-hike"


def test_preview_file_mirrors_render_files_colour_convention(workspace_root: Path) -> None:
    ws = Workspace.discover(root_override=workspace_root)
    assert ws.preview_file("take-a-hike", "flat-lay-01", "black", "deadbeef") == (
        ws.preview_dir("take-a-hike") / "flat-lay-01" / "black-deadbeef.png"
    )
    assert ws.preview_file("take-a-hike", "colour-chart-01", None, "deadbeef") == (
        ws.preview_dir("take-a-hike") / "colour-chart-01" / "scene-deadbeef.png"
    )


def test_preview_file_refuses_a_hash_that_is_not_a_valid_segment(workspace_root: Path) -> None:
    """A caller must strip a hash's `sha256:` prefix before handing it here --
    a colon is refused the same way a `..` component in a name would be."""
    ws = Workspace.discover(root_override=workspace_root)
    with pytest.raises(InvalidNameError):
        ws.preview_file("take-a-hike", "flat-lay-01", "black", "sha256:deadbeef")


def test_remove_tree_survives_a_read_only_directory(tmp_path: Path) -> None:
    """A tree this project owns is deletable whatever flag the filesystem has
    put on it -- a workspace synced by Google Drive arrives with every
    directory marked read-only, which Windows turns into a bare "Access is
    denied" on the final `rmdir` of each one.

    The two platforms refuse at different points, which is why the fixture has
    both a read-only directory and a file inside it: Windows blocks removing
    the directory itself, POSIX blocks unlinking its entries. One assertion
    covers both.
    """
    root = tmp_path / "listing"
    protected = root / "renders"
    protected.mkdir(parents=True)
    (protected / "black.png").write_bytes(b"png")
    protected.chmod(stat.S_IREAD | stat.S_IEXEC)

    remove_tree(root)

    assert not root.exists()


def test_remove_tree_still_raises_a_refusal_it_cannot_widen(tmp_path: Path) -> None:
    """The hook widens exactly one refusal. A path that is not there at all is
    not a permission problem, and must not be quietly swallowed on the way to
    looking like a successful delete."""
    with pytest.raises(FileNotFoundError):
        remove_tree(tmp_path / "never-existed")


def test_remove_listing_survives_a_read_only_listing_directory(workspace_root: Path) -> None:
    """The bug as a seller met it: Delete wiped `listing.yaml` and then failed
    on the directory, leaving an empty husk the listings table still showed."""
    ws = Workspace.discover(root_override=workspace_root)
    listing_dir = ws.listing_dir("take-a-hike")
    listing_dir.chmod(stat.S_IREAD | stat.S_IEXEC)

    ws.remove_listing("take-a-hike")

    assert not listing_dir.exists()


def test_remove_listing_wipes_its_previews_too(workspace_root: Path) -> None:
    ws = Workspace.discover(root_override=workspace_root)
    preview = ws.preview_file("take-a-hike", "flat-lay-01", "black", "deadbeef")
    preview.parent.mkdir(parents=True)
    preview.write_bytes(b"png")

    ws.remove_listing("take-a-hike")

    assert not ws.preview_dir("take-a-hike").exists()
