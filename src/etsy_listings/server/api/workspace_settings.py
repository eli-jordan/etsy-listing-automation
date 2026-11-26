from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse

from etsy_listings.core.ai.discovery import ModelCatalogs, ModelDiscovery
from etsy_listings.core.application import (
    settings_save,
    template_position_impact,
    workspace_settings,
)
from etsy_listings.core.application.position_coverage import cover_widened_limits
from etsy_listings.core.application.preparation.coordinator import Preparations
from etsy_listings.core.application.refusals import (
    InvalidSettingsEditError,
    SettingsRevisionConflictError,
)
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.config.settings import PROVIDER_NAMES, AiProviderSettings, SettingsProblem
from etsy_listings.core.render.positions import PositionLimits
from etsy_listings.server.api import app_state
from etsy_listings.server.api.schemas import (
    ListingOutsideBody,
    SettingsSaveRefusal,
    TemplatePositionImpactRequest,
    TemplatePositionImpactResponse,
    WorkspaceSettingsPatch,
    WorkspaceSettingsResponse,
)

router = APIRouter(prefix="/api/admin/settings", tags=["admin"])


@router.get("/models")
def model_catalogs(request: Request, *, refresh: bool = False) -> ModelCatalogs:
    discovery: ModelDiscovery = request.app.state.model_discovery
    return discovery.read(refresh=refresh)


def _response(view: workspace_settings.SettingsView) -> WorkspaceSettingsResponse:
    return WorkspaceSettingsResponse(
        revision=view.revision,
        template_positions=view.settings.template_positions,
        concurrency=view.settings.batch_ai.concurrency,
        weights=view.settings.market_seo.weights.model_dump(),
        default_weights=workspace_settings.default_weights(),
        providers=list(view.settings.ai.providers)
        + [
            AiProviderSettings(name=name, enabled=False)
            for name in PROVIDER_NAMES
            if name not in {p.name for p in view.settings.ai.providers}
        ],
        step_limit_minutes=view.settings.ai.step_limit_minutes,
        run_limit_minutes=view.settings.ai.run_limit_minutes,
        backup=view.settings.backup,
    )


@router.get("")
def read_settings(request: Request) -> WorkspaceSettingsResponse:
    try:
        return _response(workspace_settings.read_settings(request.app.state.workspace))
    except ConfigLoadError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@router.patch(
    "",
    response_model=WorkspaceSettingsResponse,
    responses={412: {"model": SettingsSaveRefusal}, 422: {"model": SettingsSaveRefusal}},
)
def edit_settings(
    request: Request, body: WorkspaceSettingsPatch, background: BackgroundTasks
) -> WorkspaceSettingsResponse | JSONResponse:
    """Save ``changes`` against ``revision``: 412 when the file changed since,
    422 for an edit it refuses. What the save sets off is ``settings_save``'s;
    this hands it the host's coordinators, and coverage jobs it queues are
    queued after the response."""
    keys = {
        "concurrency": workspace_settings.CONCURRENCY,
        "weights": workspace_settings.WEIGHTS,
        "providers": workspace_settings.PROVIDERS,
        "step_limit_minutes": workspace_settings.STEP_LIMIT,
        "run_limit_minutes": workspace_settings.RUN_LIMIT,
        "template_positions": workspace_settings.TEMPLATE_POSITIONS,
        "backup_destinations": workspace_settings.BACKUP_DESTINATIONS,
        "backup_interval_hours": workspace_settings.BACKUP_INTERVAL,
        "backup_retention": workspace_settings.BACKUP_RETENTION,
    }
    changes = {
        keys[key]: value for key, value in body.changes.model_dump(exclude_unset=True).items()
    }
    coordinators = settings_save.SettingsCoordinators(
        ai_queue=request.app.state.ai.queue,
        backups=app_state.backups(request),
        coverage=_AfterResponse(request.app.state.preparations, background),
    )
    try:
        view = settings_save.save_settings(
            request.app.state.workspace,
            expected_revision=body.revision,
            changes=changes,
            coordinators=coordinators,
        )
    except SettingsRevisionConflictError as exc:
        return JSONResponse(
            status_code=412,
            content=SettingsSaveRefusal(kind="stale", message=str(exc)).model_dump(),
        )
    except InvalidSettingsEditError as exc:
        return _invalid(exc)
    return _response(view)


class _AfterResponse:
    """Coverage queued once the save has answered, so a slow template scan
    never holds the response."""

    def __init__(self, preparations: Preparations, background: BackgroundTasks) -> None:
        self._preparations = preparations
        self._background = background

    def cover_widened(self, saved: PositionLimits, limits: PositionLimits) -> None:
        self._background.add_task(cover_widened_limits, self._preparations, saved, limits)


@router.post(
    "/template-positions/impact",
    response_model=TemplatePositionImpactResponse,
    responses={422: {"model": SettingsSaveRefusal}},
)
def template_positions_impact(
    request: Request, body: TemplatePositionImpactRequest
) -> TemplatePositionImpactResponse | JSONResponse:
    """A read for Settings' confirmation (template positions PR 5): who the
    candidate limits would block, and which Marigold templates would need
    model inference to cover them."""
    try:
        limits = template_position_impact.candidate_limits(body.limits)
    except InvalidSettingsEditError as exc:
        return _invalid(exc)
    impact = template_position_impact.template_position_impact(request.app.state.workspace, limits)
    if isinstance(impact, SettingsProblem):
        return JSONResponse(
            status_code=422,
            content=SettingsSaveRefusal(kind="invalid", message=impact.message).model_dump(),
        )
    return TemplatePositionImpactResponse(
        outside=[
            ListingOutsideBody(listing=row.listing, positions=list(row.positions))
            for row in impact.outside
        ],
        templates_needing_inference=list(impact.templates_needing_inference),
    )


def _invalid(exc: InvalidSettingsEditError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=SettingsSaveRefusal(
            kind="invalid", message=str(exc), field_errors=exc.field_errors
        ).model_dump(),
    )
