"""Settings reads and revision-checked saves (Admin plan PR 4, ADR-0055)."""

from contextlib import suppress

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse

from etsy_listings.core.ai.discovery import ModelCatalogs, ModelDiscovery
from etsy_listings.core.application import template_position_impact, workspace_settings
from etsy_listings.core.application.position_coverage import cover_widened_limits
from etsy_listings.core.application.refusals import (
    InvalidSettingsEditError,
    SettingsRevisionConflictError,
)
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.config.settings import PROVIDER_NAMES, AiProviderSettings
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
    """Save ``changes`` against ``revision``. Wider template position limits
    queue, after the response, coverage inference for each positioned Marigold
    template whose evidence misses them (option B, ADR-0058); narrowing
    queues nothing."""
    keys = {
        "concurrency": workspace_settings.CONCURRENCY,
        "weights": workspace_settings.WEIGHTS,
        "providers": workspace_settings.PROVIDERS,
        "step_limit_minutes": workspace_settings.STEP_LIMIT,
        "run_limit_minutes": workspace_settings.RUN_LIMIT,
        "template_positions": workspace_settings.TEMPLATE_POSITIONS,
    }
    changes = {
        keys[key]: value for key, value in body.changes.model_dump(exclude_unset=True).items()
    }
    workspace = request.app.state.workspace
    before = None
    if workspace_settings.TEMPLATE_POSITIONS in changes:
        with suppress(ConfigLoadError):
            before = workspace.load_settings().template_positions
    try:
        view = workspace_settings.edit_settings(
            workspace,
            expected_revision=body.revision,
            changes=changes,
        )
    except SettingsRevisionConflictError as exc:
        return JSONResponse(
            status_code=412,
            content=SettingsSaveRefusal(kind="conflict", message=str(exc)).model_dump(),
        )
    except InvalidSettingsEditError as exc:
        return _invalid(exc)
    # ADR-0048: a newly available slot can dispatch immediately. Waking never
    # stops active runs when the seller lowered the limit.
    if workspace_settings.CONCURRENCY in changes:
        request.app.state.ai.queue.wake()
    if before is not None:
        background.add_task(
            cover_widened_limits,
            request.app.state.preparations,
            before,
            view.settings.template_positions,
        )
    return _response(view)


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
