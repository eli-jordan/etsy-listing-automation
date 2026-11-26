"""Every rule a draft answers to, for the two pictures of one. A frame may show
unsaved geometry and masks, so it needs a draft of the same saved calibration.
A full-size scene is the prepared render, so what it asks for must be prepared.
"""

from dataclasses import dataclass

from etsy_listings.core.application.refusals import TemplatePreviewKindMismatchError
from etsy_listings.core.preparation.artifacts import PreparationInputs
from etsy_listings.core.render import (
    AnyTemplate,
    BoundingBox,
    MarigoldRenderer,
    MultipleTemplate,
    PreparationRequiredError,
)
from etsy_listings.core.workspace.calibration import Calibration, CalibrationStore, MaskEdit


@dataclass(frozen=True)
class EditorDraft:
    config: AnyTemplate
    revision: str
    mask_edits: list[MaskEdit]
    colour: str | None = None


def drawn_against(
    store: CalibrationStore, name: str, saved: Calibration, draft: EditorDraft
) -> bool:
    if saved.revision == draft.revision:
        return True
    relabelled = saved.config.model_copy(update={"labels": draft.config.labels})
    return store.revision(name, relabelled) == draft.revision


def previewable_renderer(
    store: CalibrationStore, name: str, saved: Calibration, draft: EditorDraft
) -> MarigoldRenderer:
    config = draft.config
    if not drawn_against(store, name, saved, draft):
        raise PreparationRequiredError("Calibration changed; refresh the editor preview")
    if config.kind != saved.config.kind or not isinstance(config.renderer, MarigoldRenderer):
        raise PreparationRequiredError("Save the renderer selection before previewing")
    if (
        not isinstance(saved.config.renderer, MarigoldRenderer)
        or config.renderer.config.inference != saved.config.renderer.config.inference
    ):
        raise PreparationRequiredError("Prepare changed inference settings before previewing")
    return config.renderer


def prepared_renderer(saved: AnyTemplate, requested: AnyTemplate) -> MarigoldRenderer:
    if requested.kind != saved.kind:
        raise TemplatePreviewKindMismatchError(saved.kind)
    if not isinstance(requested.renderer, MarigoldRenderer) or not isinstance(
        saved.renderer, MarigoldRenderer
    ):
        raise PreparationRequiredError("Save the Marigold renderer selection before rendering")
    return requested.renderer


def check_prepared_geometry(
    requested: AnyTemplate, renderer: MarigoldRenderer, inputs: PreparationInputs
) -> None:
    quads = {key: tuple((p.x, p.y) for p in box) for key, box in placement_boxes(requested)}
    expected = {p.id: p.quad for p in inputs.placements}
    if quads != expected or renderer.config.inference != inputs.inference:
        raise PreparationRequiredError(
            "Save geometry and inference settings, then rebuild or prepare the template"
        )


def placement_boxes(config: AnyTemplate) -> list[tuple[str | None, BoundingBox]]:
    if isinstance(config, MultipleTemplate):
        return [(p.id, p.bounding_box) for p in config.placements]
    return [(None, config.bounding_box)]
