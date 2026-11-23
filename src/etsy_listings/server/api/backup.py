"""The backup status, history, Back up now, set-up and repair
(workspace-backup plan, PR 5).

``GET /api/backup`` is the one status source for the Backup page, the
banner on every other page and both nav icons (interactions, *What the
production implementation must finish*). Setup's edits are not here: they
save through ``PATCH /api/admin/settings`` and its revision check.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from etsy_listings.core.application import backup_setup
from etsy_listings.core.application.backup_overview import BackupOverview
from etsy_listings.core.application.refusals import InvalidSettingsEditError
from etsy_listings.core.errors import ConflictError, RefusedError, StaleError
from etsy_listings.server.api import app_state
from etsy_listings.server.api.schemas import (
    BackupHistoryResponse,
    BackupRepairRequest,
    BackupRepairResponse,
    BackupSetUpRequest,
    SettingsSaveRefusal,
)

router = APIRouter(prefix="/api/backup", tags=["backup"])


@router.get("")
def backup_status(request: Request) -> BackupOverview:
    return app_state.backups(request).overview()


@router.get("/history")
def backup_history(request: Request) -> BackupHistoryResponse:
    return BackupHistoryResponse(runs=app_state.backups(request).history())


@router.post("/run", status_code=202)
def back_up_now(request: Request) -> BackupOverview:
    """Start a backup; 409 while another backup operation runs."""
    backups = app_state.backups(request)
    backups.run_now()
    return backups.overview()


@router.post(
    "/setup",
    status_code=202,
    response_model=BackupOverview,
    responses={
        409: {"model": SettingsSaveRefusal},
        412: {"model": SettingsSaveRefusal},
        422: {"model": SettingsSaveRefusal},
    },
)
def set_up(request: Request, body: BackupSetUpRequest) -> BackupOverview | JSONResponse:
    """Write the ``backup:`` block and the password, create the repository
    and the destination folders, then start the first backup. Refuses a
    short password (422), a folder that holds files (409) and a destination
    whose parent is missing (422), writing nothing."""
    backups = app_state.backups(request)
    answers = backup_setup.BackupSetUp(
        repository=Path(body.repository),
        destinations=tuple(Path(path) for path in body.destinations),
        interval_hours=body.interval_hours,
        retention=body.retention,
        password=body.password,
    )
    try:
        backups.set_up(answers, expected_revision=body.revision)
    except StaleError as exc:
        return _refusal(412, "conflict", exc)
    except ConflictError as exc:
        return _refusal(409, "conflict", exc)
    except RefusedError as exc:
        fields = exc.field_errors if isinstance(exc, InvalidSettingsEditError) else {}
        return _refusal(422, "invalid", exc, fields)
    return backups.overview()


@router.post("/repair")
def repair(request: Request, body: BackupRepairRequest) -> BackupRepairResponse:
    """Set aside a destination's changed and unexpected files and copy it
    again (spec, *Changed and unexpected files*). Answers when it ends."""
    result = app_state.backups(request).repair(Path(body.destination))
    return BackupRepairResponse(
        set_aside=None if result.set_aside is None else str(result.set_aside),
        moved=list(result.moved),
        outcome=result.copy.outcome,
        message=result.copy.message,
    )


def _refusal(
    status: int,
    kind: Literal["conflict", "invalid"],
    exc: Exception,
    field_errors: dict[str, str] | None = None,
) -> JSONResponse:
    """Set-up answers as a settings save does, with the field it refuses."""
    refusal = SettingsSaveRefusal(kind=kind, message=str(exc), field_errors=field_errors or {})
    return JSONResponse(status_code=status, content=refusal.model_dump())
