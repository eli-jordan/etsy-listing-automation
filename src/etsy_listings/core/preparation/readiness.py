"""Whether a saved template can render, for every caller that asks.

Authoring status, listing checks, the render stage and the template catalogue
all ask here rather than checking the renderer first: a Photo warp template is
``not_required`` without any file read, and a Marigold template is validated
against its one fixed generation without prediction cache or model access.
Every cause is a typed :data:`ReadinessReason`, never a parsed message.
"""

from dataclasses import dataclass

from PIL import Image

from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.preparation.artifacts import (
    ArtifactError,
    Artifacts,
    IncompatibleDimensions,
    Readiness,
    ReadinessReason,
)
from etsy_listings.core.render.config import (
    AnyTemplate,
    ColourMatrixTemplate,
    MultipleTemplate,
    PhotoWarpRenderer,
)
from etsy_listings.core.workspace.calibration import CalibrationStore, MaskPhotoMismatch
from etsy_listings.core.workspace.workspace import Workspace

__all__ = [
    "Readiness",
    "ReadinessReason",
    "SavedPreparationFacts",
    "catalog_readiness",
    "saved_preparation_facts",
    "template_readiness",
]

_NOT_REQUIRED = Readiness("not_required")


@dataclass(frozen=True)
class SavedPreparationFacts:
    maps: Readiness
    prepared_engine: str | None = None


def catalog_readiness(config: AnyTemplate) -> Readiness | None:
    """What is known from the configuration alone, for a catalogue that reads
    metadata only: ``None`` means the maps must be validated to answer."""
    return _NOT_REQUIRED if isinstance(config.renderer, PhotoWarpRenderer) else None


def template_readiness(workspace: Workspace, name: str, config: AnyTemplate) -> Readiness:
    """Whether ``name``, already loaded as ``config``, can render now."""
    known = catalog_readiness(config)
    return known if known is not None else saved_preparation_facts(workspace, name).maps


def saved_preparation_facts(workspace: Workspace, name: str) -> SavedPreparationFacts:
    """Validate one fixed generation without prediction cache or model access."""
    store = CalibrationStore(workspace)
    artifacts = Artifacts(workspace)
    with store.lock(name):
        try:
            config = store.config(name)
            known = catalog_readiness(config)
            if known is not None:
                return SavedPreparationFacts(known)
            if isinstance(config, MultipleTemplate) and not config.placements:
                return SavedPreparationFacts(
                    Readiness(
                        "needs_preparation",
                        "missing_placements",
                        "Add a placement before preparing the template",
                    )
                )
            inputs = artifacts.saved_inputs(name)
            prepared_engine = None
            try:
                manifest = artifacts.inspect(name, inputs)
                maps = Readiness("ready", content_digest=manifest.content_digest)
                engine = manifest.provenance.get("engine_version")
                prepared_engine = engine if isinstance(engine, str) else None
            except ArtifactError:
                maps = artifacts.readiness(name, inputs)
            if isinstance(config, ColourMatrixTemplate):
                # Every colour shares the main photo's maps, so every photo
                # must match its size, not only the one a scene asks for.
                for photo in workspace.template_photos(name):
                    with Image.open(photo) as image:
                        if image.size != (inputs.photo.width, inputs.photo.height):
                            return SavedPreparationFacts(
                                Readiness(
                                    "out_of_date",
                                    IncompatibleDimensions.reason,
                                    "Shared colour photo dimensions differ from the main photo. "
                                    "Use matching photos or separate templates.",
                                )
                            )
            return SavedPreparationFacts(maps, prepared_engine)
        except (UserFacingError, ValueError, OSError) as exc:
            reason: ReadinessReason = ArtifactError.reason
            if isinstance(exc, ArtifactError):
                reason = exc.reason
            elif isinstance(exc, MaskPhotoMismatch):
                reason = "photo_changed"
            return SavedPreparationFacts(Readiness("out_of_date", reason, str(exc)))
