"""Read-only authoring facts and masks, independent of host transport."""

from dataclasses import dataclass

from PIL import Image

from etsy_listings.core.application.mockup_templates import require_template
from etsy_listings.core.application.preparation.coordinator import Preparations
from etsy_listings.core.application.preparation.models import TERMINAL, Job
from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.preparation.artifacts import ArtifactError, Readiness
from etsy_listings.core.render.config import (
    ColourMatrixTemplate,
    MultipleTemplate,
    PhotoWarpRenderer,
)
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import CalibrationStore, SavedMask


@dataclass(frozen=True)
class PlacementState:
    placement_id: str | None
    mask_available: bool
    mask_reason: str | None
    undo_count: int


@dataclass(frozen=True)
class PreparationView:
    template: str
    config_revision: str
    main_photo: str
    maps: Readiness
    placements: list[PlacementState]
    active_job: Job | None
    latest_job: Job | None
    renderer_settings: dict[str, object]
    prepared_engine: str | None


def preparation_view(preparations: Preparations, name: str) -> PreparationView:
    workspace = preparations.workspace
    require_template(workspace, name)
    store = CalibrationStore(workspace)
    with store.lock(name):
        saved = store.read(name)
        prepared_engine = None
        if isinstance(saved.config.renderer, PhotoWarpRenderer):
            maps = Readiness("not_required")
        elif isinstance(saved.config, MultipleTemplate) and not saved.config.placements:
            maps = Readiness(
                "needs_preparation",
                "missing_placements",
                "Add a placement before preparing the template",
            )
        else:
            try:
                inputs = preparations.artifacts.saved_inputs(name)
                # A ready poll validates and loads one fixed generation only.
                # Failed acquisitions use the artifact reader's structured reason.
                try:
                    with preparations.artifacts.acquire(name, inputs) as acquired:
                        maps = Readiness("ready", content_digest=acquired.manifest.content_digest)
                        value = acquired.manifest.provenance.get("engine_version")
                        prepared_engine = value if isinstance(value, str) else None
                except ArtifactError:
                    maps = preparations.artifacts.readiness(name, inputs)
                if isinstance(saved.config, ColourMatrixTemplate):
                    for photo in workspace.template_photos(name):
                        with Image.open(photo) as image:
                            if image.size != (inputs.photo.width, inputs.photo.height):
                                maps = Readiness(
                                    "out_of_date",
                                    "incompatible_dimensions",
                                    "Shared colour photo dimensions differ from the main photo. "
                                    "Use matching photos or separate templates.",
                                )
                                break
            except (UserFacingError, ValueError, OSError) as exc:
                reason = "photo_changed" if "Main photo changed" in str(exc) else "invalid_artifact"
                maps = Readiness("out_of_date", reason, str(exc))
        placements = []
        for identity in store.placement_ids(saved.config):
            try:
                mask = store.mask(name, identity)
                placements.append(PlacementState(identity, True, None, mask.undo_count))
            except (UserFacingError, ValueError, OSError) as exc:
                placements.append(PlacementState(identity, False, str(exc), 0))
        jobs = preparations.list_jobs(template=name, limit=1000)
        active = next((job for job in reversed(jobs) if job.phase not in TERMINAL), None)
        return PreparationView(
            name,
            saved.revision,
            saved.main_photo,
            maps,
            placements,
            active,
            jobs[-1] if jobs else None,
            store.renderer_settings(name),
            prepared_engine,
        )


def read_mask(workspace: Workspace, name: str, placement_id: str | None) -> SavedMask:
    require_template(workspace, name)
    store = CalibrationStore(workspace)
    with store.lock(name):
        saved = store.read(name)
        if isinstance(saved.config, MultipleTemplate) != (placement_id is not None):
            raise ValueError("Mask route must match the template kind")
        return store.mask(name, placement_id)
