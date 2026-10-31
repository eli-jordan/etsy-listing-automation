"""Settings reads and revision-checked saves (Admin plan PR 4, ADR-0055)."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from etsy_listings.core.ai.discovery import ModelCatalogs, ModelDiscovery
from etsy_listings.core.application import workspace_settings
from etsy_listings.core.application.refusals import InvalidSettingsEdit, SettingsRevisionConflict
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.config.settings import PROVIDER_NAMES, AiProviderSettings
from etsy_listings.server.api.schemas import (
    SettingsSaveRefusal,
    WorkspaceSettingsPatch,
    WorkspaceSettingsResponse,
)

router = APIRouter(prefix="/api/admin/settings", tags=["admin"])


@router.get("/models", response_model=ModelCatalogs)
def model_catalogs(request: Request, refresh: bool = False) -> ModelCatalogs:
    discovery: ModelDiscovery = request.app.state.model_discovery
    return discovery.read(refresh=refresh)


def _response(view: workspace_settings.SettingsView) -> WorkspaceSettingsResponse:
    return WorkspaceSettingsResponse(
        revision=view.revision,
        concurrency=view.settings.batch_ai.concurrency,
        weights=view.settings.market_seo.weights.model_dump(),
        default_weights=workspace_settings.default_weights(),
        providers=list(view.settings.ai.providers)
        + [
            AiProviderSettings(name=name, enabled=False)
            for name in PROVIDER_NAMES
            if name not in {p.name for p in view.settings.ai.providers}
        ],
    )


@router.get("", response_model=WorkspaceSettingsResponse)
def read_settings(request: Request) -> WorkspaceSettingsResponse:
    try:
        return _response(workspace_settings.read_settings(request.app.state.workspace))
    except ConfigLoadError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@router.patch(
    "",
    response_model=WorkspaceSettingsResponse,
    responses={409: {"model": SettingsSaveRefusal}, 422: {"model": SettingsSaveRefusal}},
)
def edit_settings(
    request: Request, body: WorkspaceSettingsPatch
) -> WorkspaceSettingsResponse | JSONResponse:
    keys = {
        "concurrency": workspace_settings.CONCURRENCY,
        "weights": workspace_settings.WEIGHTS,
        "providers": workspace_settings.PROVIDERS,
    }
    changes = {
        keys[key]: value for key, value in body.changes.model_dump(exclude_unset=True).items()
    }
    try:
        view = workspace_settings.edit_settings(
            request.app.state.workspace,
            expected_revision=body.revision,
            changes=changes,
        )
    except SettingsRevisionConflict as exc:
        return JSONResponse(
            status_code=409,
            content=SettingsSaveRefusal(kind="conflict", message=str(exc)).model_dump(),
        )
    except InvalidSettingsEdit as exc:
        return JSONResponse(
            status_code=422,
            content=SettingsSaveRefusal(
                kind="invalid", message=str(exc), field_errors=exc.field_errors
            ).model_dump(),
        )
    # ADR-0048: a newly available slot can dispatch immediately. Waking never
    # stops active runs when the seller lowered the limit.
    if workspace_settings.CONCURRENCY in changes:
        request.app.state.ai.queue.wake()
    return _response(view)
