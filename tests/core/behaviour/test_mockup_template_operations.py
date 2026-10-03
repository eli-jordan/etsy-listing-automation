"""Calibrating a mockup template, called directly -- no ``TestClient``
(module-structure plan, PR 7).

What the rail lists and why a template is not calibrated yet, the kind a
folder of photos is given (and the colour slugs its filenames become,
ADR-0004), ``template.yaml`` read and saved, and the scene a preview
composites from saved or unsaved geometry. Status codes, the encoded preview
and the decode cache are the calibrator API tests' business.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from etsy_listings.core.application.mockup_templates import (
    PreviewGeometry,
    assign_kind,
    colour_report,
    compose_preview,
    list_templates,
    read_config,
    save_config,
    saved_preview,
    scaled,
    template_photo,
    template_swatch,
    unsaved_preview,
)
from etsy_listings.core.application.refusals import (
    TemplateAlreadyCalibrated,
    TemplateConfigMissing,
    TemplateKindRefused,
    TemplateMissing,
    TemplatePhotoMissing,
    TemplatePreviewKindMismatch,
)
from etsy_listings.core.config.slug import SlugCollisionError
from etsy_listings.core.render.config import (
    DisplaceConfig,
    MultipleTemplate,
    Point,
    RenderConfig,
    ShadeConfig,
    SingleTemplate,
)
from etsy_listings.core.render.io import load_design, load_template_base
from etsy_listings.core.workspace.workspace import InvalidNameError, Workspace

BOX = (Point(x=0, y=0), Point(x=100, y=0), Point(x=100, y=100), Point(x=0, y=100))


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


def _folder(
    workspace: Workspace, name: str, *filenames: str, size: tuple[int, int] = (64, 80)
) -> Path:
    """A template as one comes into being: a folder of photos."""
    directory = workspace.root / "mockup-templates" / name
    directory.mkdir(parents=True, exist_ok=True)
    for filename in filenames:
        Image.new("RGB", size, (200, 60, 60)).save(directory / filename)
    return directory


def _design(workspace: Workspace):  # noqa: ANN202
    return lambda: workspace.design_file("take-a-hike")


def _every_layer(workspace: Workspace):  # noqa: ANN202
    """A saved scene's ``design``: the one file, whatever colour a layer depicts."""
    return lambda _colour: workspace.design_file("take-a-hike")


def _overview(workspace: Workspace, name: str):  # noqa: ANN202
    return {t.name: t for t in list_templates(workspace)}[name]


class TestOverview:
    def test_a_calibrated_colour_matrix_lists_its_colours_photos_and_true_size(
        self, workspace: Workspace
    ) -> None:
        flat = _overview(workspace, "flat-lay-01")
        assert flat.kind == "colour-matrix"
        assert flat.calibrated and flat.status_reason is None
        assert flat.colours == ["black", "blue-jean", "ivory", "moss"]
        assert [(p.colour, p.file) for p in flat.photos][0] == (
            "black",
            "mockup-templates/flat-lay-01/black.png",
        )
        assert (flat.width, flat.height) == (480, 576)

    def test_a_fixed_scene_has_one_uncoloured_photo(self, workspace: Workspace) -> None:
        chart = _overview(workspace, "colour-chart-01")
        assert [(p.colour, p.file) for p in chart.photos] == [
            (None, "mockup-templates/colour-chart-01/scene.png")
        ]
        assert chart.colours == ["black", "moss"]

    def test_a_folder_with_no_config_needs_a_kind(self, workspace: Workspace) -> None:
        _folder(workspace, "fresh")
        fresh = _overview(workspace, "fresh")
        assert (fresh.kind, fresh.has_config, fresh.calibrated) == (None, False, False)
        assert fresh.status_reason == "no kind set"
        assert (fresh.width, fresh.height) == (None, None)

    @pytest.mark.parametrize(
        ("colours", "reason"),
        [
            ([], "no boxes"),
            (["", "moss"], "1 box has no colour"),
            (["", " "], "2 boxes have no colour"),
        ],
    )
    def test_an_unfinished_multiple_says_what_is_missing(
        self, workspace: Workspace, colours: list[str], reason: str
    ) -> None:
        config = read_config(workspace, "colour-chart-01").config
        assert isinstance(config, MultipleTemplate)
        placements = [
            p.model_copy(update={"colour": c})
            for p, c in zip(config.placements, colours, strict=False)
        ]
        save_config(
            workspace, "colour-chart-01", config.model_copy(update={"placements": placements})
        )
        assert _overview(workspace, "colour-chart-01").status_reason == reason

    def test_an_unreadable_photo_leaves_the_template_listable(self, workspace: Workspace) -> None:
        broken = _folder(workspace, "broken")
        (broken / "scene.png").write_bytes(b"not a png")
        assert _overview(workspace, "broken").width is None


class TestAssignKind:
    def test_colour_matrix_renames_photos_to_their_slugs_and_starts_a_box(
        self, workspace: Workspace
    ) -> None:
        directory = _folder(workspace, "messy", "Heather Grey.png", "Forest.png")
        config = assign_kind(workspace, "messy", "colour-matrix")
        assert config.kind == "colour-matrix"
        assert len(config.bounding_box) == 4
        # The case-only rename too, via a staging name (Windows is case-blind).
        assert sorted(p.name for p in directory.glob("*.png")) == ["forest.png", "heather-grey.png"]
        assert read_config(workspace, "messy").config == config

    def test_exceptions_yaml_decides_the_slug(self, workspace: Workspace) -> None:
        (workspace.root / "exceptions.yaml").write_text(
            "Heather Grey: hthr-gry\n", encoding="utf-8"
        )
        directory = _folder(workspace, "messy", "Heather Grey.png")
        assert [r.colour for r in colour_report(workspace, "messy")] == ["hthr-gry"]
        assign_kind(workspace, "messy", "colour-matrix")
        assert [p.name for p in directory.glob("*.png")] == ["hthr-gry.png"]

    def test_two_photos_on_one_slug_are_refused_and_nothing_moves(
        self, workspace: Workspace
    ) -> None:
        directory = _folder(workspace, "messy", "Heather Grey.png", "Heather-Grey.png")
        with pytest.raises(SlugCollisionError, match="heather-grey"):
            assign_kind(workspace, "messy", "colour-matrix")
        assert sorted(p.name for p in directory.glob("*.png")) == [
            "Heather Grey.png",
            "Heather-Grey.png",
        ]
        assert not workspace.template_config_file("messy").exists()

    def test_single_makes_the_lone_photo_the_scene(self, workspace: Workspace) -> None:
        directory = _folder(workspace, "fresh", "some-shot.png")
        assert isinstance(assign_kind(workspace, "fresh", "single"), SingleTemplate)
        assert (directory / "scene.png").is_file()
        assert not (directory / "some-shot.png").exists()

    def test_multiple_starts_with_no_boxes(self, workspace: Workspace) -> None:
        _folder(workspace, "fresh", "chart.png")
        config = assign_kind(workspace, "fresh", "multiple")
        assert isinstance(config, MultipleTemplate) and config.placements == []

    def test_a_scene_kind_refuses_a_set_of_photos(self, workspace: Workspace) -> None:
        _folder(workspace, "fresh", "a.png", "b.png")
        with pytest.raises(TemplateKindRefused, match="single kind expects one photo, found 2"):
            assign_kind(workspace, "fresh", "single")

    def test_an_empty_folder_is_refused(self, workspace: Workspace) -> None:
        _folder(workspace, "empty")
        with pytest.raises(TemplateKindRefused, match="no photos in 'empty'"):
            assign_kind(workspace, "empty", "single")

    def test_a_configured_template_keeps_its_kind(self, workspace: Workspace) -> None:
        before = workspace.template_config_file("flat-lay-01").read_bytes()
        with pytest.raises(TemplateAlreadyCalibrated, match="delete it to change kind"):
            assign_kind(workspace, "flat-lay-01", "single")
        assert workspace.template_config_file("flat-lay-01").read_bytes() == before

    def test_an_unknown_template_and_an_unusable_name_are_refused(
        self, workspace: Workspace
    ) -> None:
        with pytest.raises(TemplateMissing, match="no template 'nope'"):
            assign_kind(workspace, "nope", "single")
        with pytest.raises(InvalidNameError):
            assign_kind(workspace, "bad:name", "single")


class TestColourReport:
    def test_reports_each_photo_and_flags_a_filename_that_is_not_a_slug(
        self, workspace: Workspace
    ) -> None:
        directory = workspace.root / "mockup-templates" / "flat-lay-01"
        Image.new("RGB", (8, 8)).save(directory / "Heather Grey.png")
        rows = {r.filename: (r.colour, r.clean) for r in colour_report(workspace, "flat-lay-01")}
        assert rows["black.png"] == ("black", True)
        assert rows["Heather Grey.png"] == ("heather-grey", False)
        # Reporting only.
        assert (directory / "Heather Grey.png").is_file()

    def test_a_scene_is_not_a_colour(self, workspace: Workspace) -> None:
        assert all(r.filename != "scene.png" for r in colour_report(workspace, "colour-chart-01"))


class TestConfig:
    def test_a_saved_config_reads_back_with_when_it_was_written(self, workspace: Workspace) -> None:
        saved = read_config(workspace, "flat-lay-01")
        moved = saved.config.model_copy(
            update={
                "bounding_box": (
                    Point(x=10, y=10),
                    Point(x=200, y=10),
                    Point(x=200, y=200),
                    Point(x=10, y=200),
                )
            }
        )
        save_config(workspace, "flat-lay-01", moved)
        again = read_config(workspace, "flat-lay-01")
        assert again.config == moved
        assert again.modified_at.timestamp() == pytest.approx(
            workspace.template_config_file("flat-lay-01").stat().st_mtime
        )

    def test_a_folder_with_no_config_is_absent_not_broken(self, workspace: Workspace) -> None:
        _folder(workspace, "fresh", "black.png")
        with pytest.raises(TemplateConfigMissing, match="no template.yaml for 'fresh'"):
            read_config(workspace, "fresh")

    def test_saving_needs_a_template_to_save_into(self, workspace: Workspace) -> None:
        with pytest.raises(TemplateMissing):
            save_config(workspace, "nope", SingleTemplate(bounding_box=BOX))
        assert not (workspace.root / "mockup-templates" / "nope").exists()


class TestPreviewScene:
    def test_unsaved_geometry_must_be_the_template_s_own_kind(self, workspace: Workspace) -> None:
        geometry = PreviewGeometry(kind="colour-matrix", colour="black", boxes=(BOX,))
        with pytest.raises(TemplatePreviewKindMismatch, match="expected a multiple preview body"):
            unsaved_preview(workspace, "colour-chart-01", geometry, design=_design(workspace))

    def test_unsaved_geometry_becomes_one_layer_per_box(self, workspace: Workspace) -> None:
        shade = ShadeConfig(enabled=False)
        scene = unsaved_preview(
            workspace,
            "colour-chart-01",
            PreviewGeometry(kind="multiple", boxes=(BOX, BOX), shade=shade),
            design=_design(workspace),
        )
        assert [layer.shade for layer in scene.layers] == [shade, shade]
        assert scene.photo.path == workspace.template_scene_image("colour-chart-01")

    def test_a_colour_with_no_photo_is_refused(self, workspace: Workspace) -> None:
        with pytest.raises(TemplatePhotoMissing, match="no mockup photo for colour 'nope'"):
            unsaved_preview(
                workspace,
                "flat-lay-01",
                PreviewGeometry(kind="colour-matrix", colour="nope", boxes=(BOX,)),
                design=_design(workspace),
            )

    def test_the_design_is_resolved_after_the_kind_and_before_the_photo(
        self, workspace: Workspace
    ) -> None:
        """The order the calibrator's route has always refused in."""
        asked: list[str] = []

        def unknown() -> Path:
            asked.append("design")
            raise LookupError("unknown test design")

        with pytest.raises(TemplatePreviewKindMismatch):
            unsaved_preview(
                workspace,
                "colour-chart-01",
                PreviewGeometry(kind="single", boxes=(BOX,)),
                design=unknown,
            )
        assert asked == []
        with pytest.raises(LookupError, match="unknown test design"):
            unsaved_preview(
                workspace,
                "flat-lay-01",
                PreviewGeometry(kind="colour-matrix", colour="nope", boxes=(BOX,)),
                design=unknown,
            )

    def test_saved_geometry_is_the_render_stage_s_and_ignores_a_colour_it_has_no_photo_for(
        self, workspace: Workspace
    ) -> None:
        scene = saved_preview(
            workspace, "colour-chart-01", colour="black", design=_every_layer(workspace)
        )
        config = read_config(workspace, "colour-chart-01").config
        assert isinstance(config, MultipleTemplate)
        assert list(scene.layers) == [config.render_config_for(p) for p in config.placements]
        assert scene.photo.path.name == "scene.png"

    def test_each_saved_layer_asks_for_the_file_of_the_colour_it_depicts(
        self, workspace: Workspace
    ) -> None:
        """A ``multiple`` scene's placements each name a colour, and a layer
        resolving to nothing is kept, bare, rather than dropped -- so the
        designs stay paired with the layers they print on (A35)."""
        config = read_config(workspace, "colour-chart-01").config
        assert isinstance(config, MultipleTemplate)
        asked: list[str | None] = []
        first = config.placements[0].colour

        def per_colour(colour: str | None) -> Path | None:
            asked.append(colour)
            return workspace.design_file("take-a-hike") if colour == first else None

        scene = saved_preview(workspace, "colour-chart-01", colour=None, design=per_colour)

        assert asked == [p.colour for p in config.placements]
        assert scene.designs[0] == workspace.design_file("take-a-hike")
        assert all(path is None for path in scene.designs[1:])
        assert len(scene.designs) == len(scene.layers)

    def test_saved_geometry_needs_a_config(self, workspace: Workspace) -> None:
        _folder(workspace, "fresh", "black.png")
        with pytest.raises(TemplateConfigMissing):
            saved_preview(workspace, "fresh", colour=None, design=_every_layer(workspace))

    def test_scaling_moves_the_box_and_the_displacement_with_the_canvas(self) -> None:
        cfg = RenderConfig(bounding_box=BOX, displace=DisplaceConfig(enabled=True, strength=0.8))
        smaller = scaled(cfg, 0.25)
        assert smaller.displace.strength == pytest.approx(0.2)
        assert smaller.bounding_box[2].x == pytest.approx(25)
        assert scaled(cfg, 1.0) is cfg

    def test_compose_paints_the_design_inside_the_scaled_box_and_reads_maps_only_when_asked(
        self, workspace: Workspace
    ) -> None:
        scene = saved_preview(
            workspace, "colour-chart-01", colour=None, design=_every_layer(workspace)
        )
        base = load_template_base(scene.photo.path)
        half = np.ascontiguousarray(base[::2, ::2])
        asked: list[str] = []

        def never(kind: str):  # noqa: ANN202
            def load():  # noqa: ANN202
                asked.append(kind)
                raise AssertionError(kind)

            return load

        no_maps = tuple(
            layer.model_copy(update={"shade": ShadeConfig(enabled=False)}) for layer in scene.layers
        )
        image = compose_preview(
            replace(scene, layers=no_maps),
            base=half,
            scale=0.5,
            design=load_design,
            height=never("height"),
            luminance=never("luminance"),
        )
        assert image.size == (half.shape[1], half.shape[0])
        assert asked == []
        painted = np.asarray(image.convert("RGB"), dtype=np.int16)
        changed = np.abs(painted - half.astype(np.int16)).sum(axis=2) > 24
        rows, cols = np.nonzero(changed)
        # The first placement starts at x=134 on the 960px photo: 67 at half.
        assert cols.min() >= 60


class TestPhotosAndSwatch:
    def test_a_colour_s_own_photo_or_the_template_s_preview_photo(
        self, workspace: Workspace
    ) -> None:
        assert template_photo(workspace, "flat-lay-01", "ivory").name == "ivory.png"
        assert template_photo(workspace, "colour-chart-01", None).name == "scene.png"

    def test_no_photo_is_refused_naming_what_was_asked_for(self, workspace: Workspace) -> None:
        with pytest.raises(TemplatePhotoMissing, match="no photo for 'flat-lay-01' colour 'nope'"):
            template_photo(workspace, "flat-lay-01", "nope")
        _folder(workspace, "empty")
        with pytest.raises(TemplatePhotoMissing, match="no photo for 'empty'$"):
            template_photo(workspace, "empty", None)

    def test_a_swatch_is_the_median_shade_inside_the_saved_box(self, workspace: Workspace) -> None:
        read: list[Path] = []

        def photo(path: Path):  # noqa: ANN202
            read.append(path)
            return load_template_base(path)

        hex_colour = template_swatch(workspace, "flat-lay-01", "black", photo=photo)
        assert hex_colour.startswith("#") and len(hex_colour) == 7
        assert [p.name for p in read] == ["black.png"]

    def test_only_a_colour_matrix_has_a_swatch(self, workspace: Workspace) -> None:
        with pytest.raises(TemplatePhotoMissing, match="is not a colour-matrix template"):
            template_swatch(workspace, "colour-chart-01", "black", photo=load_template_base)
        with pytest.raises(TemplatePhotoMissing, match="no photo for 'flat-lay-01' colour 'nope'"):
            template_swatch(workspace, "flat-lay-01", "nope", photo=load_template_base)
