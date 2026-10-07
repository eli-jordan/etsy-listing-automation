"""Saved map readiness shared by authoring, listing checks and deployment."""

from dataclasses import dataclass

from PIL import Image

from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.preparation.artifacts import ArtifactError, Artifacts, Readiness
from etsy_listings.core.render.config import (
    ColourMatrixTemplate,
    MultipleTemplate,
    PhotoWarpRenderer,
)
from etsy_listings.core.workspace.calibration import CalibrationStore, MaskPhotoMismatch
from etsy_listings.core.workspace.workspace import Workspace


@dataclass(frozen=True)
class SavedPreparationFacts:
    maps: Readiness
    prepared_engine: str | None = None


def saved_readiness(workspace: Workspace, name: str) -> Readiness:
    return saved_preparation_facts(workspace, name).maps


def saved_preparation_facts(workspace: Workspace, name: str) -> SavedPreparationFacts:
    """Validate one fixed generation without prediction cache or model access."""
    store = CalibrationStore(workspace)
    artifacts = Artifacts(workspace)
    with store.lock(name):
        try:
            config = store.config(name)
            if isinstance(config.renderer, PhotoWarpRenderer):
                return SavedPreparationFacts(Readiness("not_required"))
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
                with artifacts.acquire(name, inputs) as acquired:
                    maps = Readiness("ready", content_digest=acquired.manifest.content_digest)
                    engine = acquired.manifest.provenance.get("engine_version")
                    prepared_engine = engine if isinstance(engine, str) else None
            except ArtifactError:
                maps = artifacts.readiness(name, inputs)
            if isinstance(config, ColourMatrixTemplate):
                for photo in workspace.template_photos(name):
                    with Image.open(photo) as image:
                        if image.size != (inputs.photo.width, inputs.photo.height):
                            return SavedPreparationFacts(
                                Readiness(
                                    "out_of_date",
                                    "incompatible_dimensions",
                                    "Shared colour photo dimensions differ from the main photo. "
                                    "Use matching photos or separate templates.",
                                )
                            )
            return SavedPreparationFacts(maps, prepared_engine)
        except (UserFacingError, ValueError, OSError) as exc:
            reason = "photo_changed" if isinstance(exc, MaskPhotoMismatch) else "invalid_artifact"
            return SavedPreparationFacts(Readiness("out_of_date", reason, str(exc)))
