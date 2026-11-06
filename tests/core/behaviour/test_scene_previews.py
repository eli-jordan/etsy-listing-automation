"""This scene at this size, for either renderer, saved or drawn: what a host
gets back, whether a draft still matches what is saved, and how a failure to
use prepared files reaches it. Called directly with a fake decoder -- status
codes, headers and encoding are ``server/api/scene_responses.py``'s, tested
through the routes.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from etsy_listings.core.application.mockup_templates import (
    LazyMaps,
    PreviewGeometry,
    PreviewScene,
)
from etsy_listings.core.application.refusals import TemplatePreviewKindMismatchError
from etsy_listings.core.application.scene_previews import (
    DISK_IMAGES,
    EditorCanvas,
    RenderedScene,
    SceneDraft,
    SceneFrame,
    SceneLayers,
    draft_scene,
    saved_scene,
)
from etsy_listings.core.render import PreparationRequiredError, prepare_material_artwork
from etsy_listings.core.render.config import (
    AnyTemplate,
    MultipleTemplate,
    dump_template_config,
    load_template_config,
)
from etsy_listings.core.render.types import RGB, RGBA, FloatMap
from etsy_listings.core.workspace.calibration import CalibrationStore, MaskEdit, Undo
from etsy_listings.core.workspace.template_state import template_state
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.marigold import listing_with_prepared_marigold, marigold_template

SHIRT = "shirt"
FLAT = "flat-lay-01"
HALF = 0.5


class FakeDecoder:
    """Arrays with no decoding behind them, so a test reads what was asked
    for. Photos are grey; a canvas is half the photo; a design is solid red."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.photos: list[Path] = []

    def photo(self, path: Path) -> RGB:
        self.photos.append(path)
        with Image.open(path) as image:
            width, height = image.size
        return np.full((height, width, 3), 128, np.uint8)

    def design(self, path: Path) -> RGBA:
        del path
        design = np.zeros((32, 32, 4), np.uint8)
        design[..., 0] = 255
        design[..., 3] = 255
        return design

    def canvas(self, scene: PreviewScene) -> EditorCanvas:
        full = self.photo(scene.photo.path)
        base = np.ascontiguousarray(full[::2, ::2])
        flat = np.zeros(base.shape[:2], np.float32)
        return EditorCanvas(base, HALF, LazyMaps(height=lambda: flat, luminance=lambda: flat))

    def artwork(self, path: Path) -> tuple[RGBA, FloatMap]:
        design = self.design(path)
        return design, prepare_material_artwork(design)


def _design_of(workspace: Workspace):
    return lambda: workspace.design_file("take-a-hike")


def _draft(
    workspace: Workspace,
    config: AnyTemplate,
    *,
    revision: str = "",
    mask_edits: list[MaskEdit] | None = None,
    colour: str | None = None,
) -> SceneDraft:
    boxes = (
        tuple(p.bounding_box for p in config.placements)
        if isinstance(config, MultipleTemplate)
        else (config.bounding_box,)
    )
    return SceneDraft(
        geometry=PreviewGeometry(
            kind=config.kind, boxes=boxes, colour=colour, renderer=config.renderer
        ),
        document=dump_template_config(config),
        revision=revision,
        mask_edits=mask_edits or [],
        design=_design_of(workspace),
    )


def _moved(config: AnyTemplate) -> AnyTemplate:
    box = tuple(p.model_copy(update={"x": p.x + 14, "y": p.y + 14}) for p in config.bounding_box)
    return config.model_copy(update={"bounding_box": box})


def _save(store: CalibrationStore, config: AnyTemplate, request_id: str) -> None:
    store.save(
        SHIRT,
        config,
        expected_revision=store.read(SHIRT).revision,
        request_id=request_id,
    )


class TestASavedPhotoWarpScene:
    @pytest.fixture
    def workspace(self, workspace_root: Path) -> Workspace:
        return Workspace.discover(root_override=workspace_root)

    def _layers(self, workspace: Workspace) -> SceneLayers:
        return SceneLayers("black", lambda _colour: _design_of(workspace)())

    def test_at_full_size_it_is_the_rendered_png_with_its_identity(
        self, workspace: Workspace
    ) -> None:
        picture = saved_scene(
            workspace, FLAT, self._layers(workspace), size="full", images=FakeDecoder(workspace)
        )

        assert isinstance(picture, RenderedScene)
        assert picture.png.startswith(b"\x89PNG")
        assert picture.render_identity.startswith("sha256:")
        assert picture.generation_id is None

    def test_at_editor_size_it_is_a_frame_on_the_decoders_canvas(
        self, workspace: Workspace
    ) -> None:
        images = FakeDecoder(workspace)

        picture = saved_scene(
            workspace, FLAT, self._layers(workspace), size="editor", images=images
        )

        assert isinstance(picture, SceneFrame)
        assert not picture.interactive
        with Image.open(images.photos[0]) as photo:
            assert picture.image.size == (round(photo.width * HALF), round(photo.height * HALF))

    def test_the_disk_decoder_finishes_the_same_frame_without_downscaling(
        self, workspace: Workspace
    ) -> None:
        picture = saved_scene(
            workspace, FLAT, self._layers(workspace), size="editor", images=DISK_IMAGES
        )

        assert isinstance(picture, SceneFrame)
        with Image.open(workspace.scene_photo(FLAT, "black").path) as photo:
            assert picture.image.size == photo.size


def test_a_saved_marigold_scene_has_one_size_and_names_its_generation(
    workspace_root: Path,
) -> None:
    workspace = listing_with_prepared_marigold(workspace_root)
    layers = SceneLayers(None, lambda _colour: _design_of(workspace)())

    full = saved_scene(workspace, SHIRT, layers, size="full", images=DISK_IMAGES)
    editor = saved_scene(workspace, SHIRT, layers, size="editor", images=FakeDecoder(workspace))

    assert isinstance(full, RenderedScene)
    assert editor == full
    assert full.generation_id
    assert full.config_revision == CalibrationStore(workspace).read(SHIRT).revision


@pytest.mark.parametrize("kind", ["single", "colour-matrix", "multiple"])
def test_a_photo_warp_draft_previews_before_a_renderer_switch_is_saved(
    workspace_root: Path, kind: str
) -> None:
    workspace = marigold_template(workspace_root, kind)
    store = CalibrationStore(workspace)
    saved = store.read(SHIRT)
    switched = load_template_config(
        {**dump_template_config(saved.config), "renderer": {"type": "photo-warp", "config": {}}}
    )
    colour = "navy" if kind == "colour-matrix" else None

    picture = draft_scene(
        workspace,
        SHIRT,
        _draft(workspace, switched, colour=colour),
        size="editor",
        images=FakeDecoder(workspace),
    )

    assert isinstance(picture, SceneFrame)
    assert store.read(SHIRT).revision == saved.revision


class TestAMarigoldDraftFrame:
    @pytest.fixture
    def workspace(self, workspace_root: Path) -> Workspace:
        return listing_with_prepared_marigold(workspace_root)

    @pytest.fixture
    def store(self, workspace: Workspace) -> CalibrationStore:
        return CalibrationStore(workspace)

    def _frame(self, workspace: Workspace, draft: SceneDraft) -> SceneFrame:
        picture = draft_scene(workspace, SHIRT, draft, size="editor", images=FakeDecoder(workspace))
        assert isinstance(picture, SceneFrame)
        return picture

    def test_it_is_interactive_and_shows_unsaved_geometry(
        self, workspace: Workspace, store: CalibrationStore
    ) -> None:
        saved = store.read(SHIRT)

        before = self._frame(workspace, _draft(workspace, saved.config, revision=saved.revision))
        moved = self._frame(
            workspace, _draft(workspace, _moved(saved.config), revision=saved.revision)
        )

        assert before.interactive
        assert before.image.tobytes() != moved.image.tobytes()

    def test_it_outlives_a_label_save(self, workspace: Workspace, store: CalibrationStore) -> None:
        """A draft names the revision it was read at, with that revision's
        labels. A label save moves the revision but nothing a preview draws, so
        the frame on screen, and one in flight as the save lands, stays good."""
        saved = store.read(SHIRT)
        draft = _draft(workspace, saved.config, revision=saved.revision)
        before = self._frame(workspace, draft)

        _save(store, saved.config.model_copy(update={"labels": ["cosy"]}), "one")
        _save(store, saved.config.model_copy(update={"labels": ["cosy", "warm"]}), "two")

        assert self._frame(workspace, draft).image.tobytes() == before.image.tobytes()

    def test_it_is_refused_after_any_other_save(
        self, workspace: Workspace, store: CalibrationStore
    ) -> None:
        saved = store.read(SHIRT)
        draft = _draft(workspace, saved.config, revision=saved.revision)

        _save(store, _moved(saved.config).model_copy(update={"labels": ["cosy"]}), "moved")

        with pytest.raises(PreparationRequiredError, match="Calibration changed"):
            self._frame(workspace, draft)

    def test_naming_labels_its_revision_never_held_is_refused(
        self, workspace: Workspace, store: CalibrationStore
    ) -> None:
        saved = store.read(SHIRT)
        relabelled = saved.config.model_copy(update={"labels": ["never held"]})
        draft = _draft(workspace, relabelled, revision=saved.revision)

        _save(store, saved.config.model_copy(update={"labels": ["cosy"]}), "one")

        with pytest.raises(PreparationRequiredError, match="Calibration changed"):
            self._frame(workspace, draft)

    def test_a_file_it_cannot_use_is_the_refusal_of_needing_preparation(
        self, workspace: Workspace, store: CalibrationStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        saved = store.read(SHIRT)
        images = FakeDecoder(workspace)

        def gone(_path: Path) -> tuple[RGBA, FloatMap]:
            raise OSError("artwork changed repeatedly")

        monkeypatch.setattr(images, "artwork", gone)
        draft = _draft(workspace, saved.config, revision=saved.revision)

        with pytest.raises(PreparationRequiredError, match="artwork changed repeatedly"):
            draft_scene(workspace, SHIRT, draft, size="editor", images=images)


class TestAMarigoldDraftAtFullSize:
    @pytest.fixture
    def workspace(self, workspace_root: Path) -> Workspace:
        return listing_with_prepared_marigold(workspace_root)

    def _full(self, workspace: Workspace, draft: SceneDraft) -> object:
        return draft_scene(workspace, SHIRT, draft, size="full", images=FakeDecoder(workspace))

    def test_it_is_the_saved_scene_when_it_matches_what_is_prepared(
        self, workspace: Workspace
    ) -> None:
        config = template_state(workspace, SHIRT).require()
        layers = SceneLayers(None, lambda _colour: _design_of(workspace)())

        picture = self._full(workspace, _draft(workspace, config))

        assert picture == saved_scene(workspace, SHIRT, layers, size="full", images=DISK_IMAGES)

    def test_unsaved_geometry_is_refused(self, workspace: Workspace) -> None:
        config = _moved(template_state(workspace, SHIRT).require())

        with pytest.raises(PreparationRequiredError, match="Save geometry"):
            self._full(workspace, _draft(workspace, config))

    def test_unsaved_strokes_are_refused(self, workspace: Workspace) -> None:
        config = template_state(workspace, SHIRT).require()
        strokes = [MaskEdit(operations=[Undo(type="undo")])]

        with pytest.raises(PreparationRequiredError, match="Save draft mask edits"):
            self._full(workspace, _draft(workspace, config, mask_edits=strokes))

    def test_a_draft_of_another_kind_is_refused(self, workspace: Workspace) -> None:
        document = dump_template_config(template_state(workspace, SHIRT).require())
        multiple = MultipleTemplate.model_validate(
            {
                "renderer": document["renderer"],
                "placements": [
                    {"id": "one", "colour": "Navy", "bounding_box": document["bounding_box"]}
                ],
            }
        )

        with pytest.raises(TemplatePreviewKindMismatchError):
            self._full(workspace, _draft(workspace, multiple))
