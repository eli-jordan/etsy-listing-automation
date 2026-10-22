"""Read-only authoring facts and masks, independent of host transport."""

from dataclasses import dataclass

from etsy_listings.core.application.mockup_templates import require_template
from etsy_listings.core.application.preparation.coordinator import Preparations
from etsy_listings.core.application.preparation.models import TERMINAL, Job
from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.preparation.artifacts import Readiness
from etsy_listings.core.preparation.readiness import saved_preparation_facts
from etsy_listings.core.render.config import MultipleTemplate
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
        facts = saved_preparation_facts(workspace, name)
        maps = facts.maps
        prepared_engine = facts.prepared_engine
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
