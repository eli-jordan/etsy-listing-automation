"""Immutable map acquisition and CPU composition for authoring previews."""

import hashlib
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from etsy_listings.core.application.mockup_templates import require_template
from etsy_listings.core.application.refusals import (
    TemplatePhotoMissing,
    TemplatePreviewKindMismatch,
)
from etsy_listings.core.preparation.artifacts import ArtifactError, Artifacts
from etsy_listings.core.render import (
    AnyTemplate,
    ColourMatrixTemplate,
    MarigoldRenderer,
    MaterialLayer,
    MultipleTemplate,
    PreparationRequired,
    load_design,
    load_template_base,
    render_marigold_scene,
)
from etsy_listings.core.render.identity import artwork_identity, prepared_scene_identity
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import CalibrationStore


@dataclass(frozen=True)
class PreparedPreview:
    image: Image.Image
    render_identity: str
    generation_id: str
    config_revision: str


def prepared_preview(
    workspace: Workspace,
    name: str,
    *,
    config: AnyTemplate | None,
    colour: str | None,
    design: Callable[[], Path],
) -> PreparedPreview:
    require_template(workspace, name)
    store = CalibrationStore(workspace)
    artifacts = Artifacts(workspace)
    # Capture saved geometry/masks/reference and the selected target once. The
    # acquired generation stays leased until the complete scene is composed.
    with ExitStack() as lease:
        with store.lock(name):
            saved = store.read(name)
            requested = config if config is not None else saved.config
            if requested.kind != saved.config.kind:
                raise TemplatePreviewKindMismatch(saved.config.kind)
            if not isinstance(requested.renderer, MarigoldRenderer) or not isinstance(
                saved.config.renderer, MarigoldRenderer
            ):
                raise PreparationRequired("Save the Marigold renderer selection before rendering")
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
            path = workspace.scene_photo(
                name, colour if isinstance(requested, ColourMatrixTemplate) else None
            ).path
            if not path.is_file():
                raise TemplatePhotoMissing("Selected target photo is missing")
            base = load_template_base(path)
            artwork = load_design(design())
            ids = (
                [p.id for p in requested.placements]
                if isinstance(requested, MultipleTemplate)
                else [None]
            )
        try:
            with store.lock(name):
                # Re-check saved inputs after image decoding, then release the
                # authoring lock while the fixed generation remains leased.
                current = artifacts.saved_inputs(name)
                if current.identity() != inputs.identity():
                    raise PreparationRequired(
                        "Calibration changed; save and prepare before rendering"
                    )
                acquired = lease.enter_context(
                    artifacts.acquire(name, inputs, target_size=(base.shape[1], base.shape[0]))
                )
            appearance = requested.renderer.config.appearance
            identity = prepared_scene_identity(
                map_content=acquired.manifest.content_digest,
                placement_ids=ids,
                artwork_digests=[artwork_identity(artwork)] * len(ids),
                photo_pixels=hashlib.sha256(base.tobytes()).hexdigest(),
                appearance=appearance,
            )
            image = render_marigold_scene(
                base,
                [MaterialLayer(artwork, acquired.maps[key], key) for key in ids],
                appearance=appearance,
            )
            return PreparedPreview(image, identity, acquired.manifest.generation_id, saved.revision)
        except ArtifactError as exc:
            raise PreparationRequired(str(exc)) from exc
