"""Previews of a template's *saved* scene, whichever renderer it uses.

:func:`saved_scene` is the one entry point for the listing editors and the
listing-template editor: it picks the renderer, so a route never has to. A
prepared scene composes through :func:`~etsy_listings.core.preparation.scenes.lease_scene`,
the render stage's own path, so a preview's identity is the rendered file's.
"""

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from etsy_listings.core.application.mockup_templates import (
    LayerDesign,
    PreviewScene,
    read_config,
    require_template,
    saved_preview,
)
from etsy_listings.core.application.refusals import (
    TemplatePhotoMissing,
    TemplatePreviewKindMismatch,
)
from etsy_listings.core.preparation.artifacts import ArtifactError, Artifacts
from etsy_listings.core.preparation.readiness import template_readiness
from etsy_listings.core.preparation.scenes import PreparedLayer, lease_scene
from etsy_listings.core.render import (
    AnyTemplate,
    ColourMatrixTemplate,
    MarigoldRenderer,
    MultipleTemplate,
    PreparationRequired,
    load_design,
    load_template_base,
    scene_colours,
)
from etsy_listings.core.render.types import RGBA
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import CalibrationStore


@dataclass(frozen=True)
class PreparedPreview:
    image: Image.Image
    render_identity: str
    generation_id: str
    config_revision: str


def saved_scene(
    workspace: Workspace, name: str, *, colour: str | None, design: LayerDesign
) -> PreviewScene | PreparedPreview:
    """``name``'s saved scene with ``design`` asked once per layer, as
    :func:`~etsy_listings.core.application.mockup_templates.saved_preview`
    asks it. Photo warp returns the scene for the host to composite from its
    image memo; Marigold returns the composed image. Refusals:
    :class:`TemplateMissing`, :class:`TemplateConfigMissing`,
    :class:`TemplatePhotoMissing`, :class:`PreparationRequired`."""
    if isinstance(read_config(workspace, name).config.renderer, MarigoldRenderer):
        return prepared_preview(workspace, name, config=None, colour=colour, design=design)
    return saved_preview(workspace, name, colour=colour, design=design)


def prepared_preview(
    workspace: Workspace,
    name: str,
    *,
    config: AnyTemplate | None,
    colour: str | None,
    design: LayerDesign,
) -> PreparedPreview:
    """A Marigold scene at ``config``'s geometry (the saved one when
    ``None``), which must match the saved, prepared inputs. ``design`` is
    asked once per layer with the colour it depicts; a layer with no file is
    left bare."""
    require_template(workspace, name)
    store = CalibrationStore(workspace)
    artifacts = Artifacts(workspace)
    # Capture saved geometry/masks/reference and the selected target once;
    # lease_scene re-checks them after the images are decoded.
    with store.lock(name):
        saved = store.read(name)
        requested = config if config is not None else saved.config
        if requested.kind != saved.config.kind:
            raise TemplatePreviewKindMismatch(saved.config.kind)
        if not isinstance(requested.renderer, MarigoldRenderer) or not isinstance(
            saved.config.renderer, MarigoldRenderer
        ):
            raise PreparationRequired("Save the Marigold renderer selection before rendering")
        readiness = template_readiness(workspace, name, saved.config)
        if not readiness.can_render:
            raise PreparationRequired(readiness.message or "Prepare the template first")
        inputs = artifacts.saved_inputs(name)
        boxes = (
            {p.id: p.bounding_box for p in requested.placements}
            if isinstance(requested, MultipleTemplate)
            else {None: requested.bounding_box}
        )
        expected = {p.id: p.quad for p in inputs.placements}
        if {
            key: tuple((p.x, p.y) for p in box) for key, box in boxes.items()
        } != expected or requested.renderer.config.inference != inputs.inference:
            raise PreparationRequired(
                "Save geometry and inference settings, then rebuild or prepare the template"
            )
        depicted = colour if isinstance(requested, ColourMatrixTemplate) else None
        path = workspace.scene_photo(name, depicted).path
        if not path.is_file():
            raise TemplatePhotoMissing("Selected target photo is missing")
        base = load_template_base(path)
        layers = _layers(requested, depicted, design)
    try:
        with lease_scene(
            workspace,
            name,
            base=base,
            layers=layers,
            appearance=requested.renderer.config.appearance,
            expected=inputs,
        ) as scene:
            return PreparedPreview(
                scene.render(), scene.identity, scene.manifest.generation_id, saved.revision
            )
    except ArtifactError as exc:
        raise PreparationRequired(str(exc)) from exc


def _layers(config: AnyTemplate, colour: str | None, design: LayerDesign) -> list[PreparedLayer]:
    decoded: dict[Path, RGBA] = {}
    layers = []
    for depicted, placement in scene_colours(config, colour):
        path = design(depicted)
        if path is None:
            continue
        if path not in decoded:
            decoded[path] = load_design(path)
        layers.append(PreparedLayer(decoded[path], placement))
    return layers
