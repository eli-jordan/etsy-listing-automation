"""The backup status, history, Back up now, set-up, repair, restore, and the
missing-repository actions (workspace-backup plan, PRs 5, 7 and 8).

``GET /api/backup`` is the one status source for the Backup page, the
banner on every other page and both nav icons (interactions, *What the
production implementation must finish*). Setup's edits are not here: they
save through ``PATCH /api/admin/settings`` and its revision check.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from etsy_listings.core.application import backup_setup
from etsy_listings.core.application.backup_coordinator import BackupCoordinator
from etsy_listings.core.application.backup_missing import (
    DestinationHoldsRepositoryError,
    Replacement,
)
from etsy_listings.core.application.backup_overview import BackupOverview
from etsy_listings.core.application.refusals import InvalidSettingsEditError
from etsy_listings.core.errors import ConflictError, RefusedError, StaleError
from etsy_listings.server.api import app_state
from etsy_listings.server.api.schemas import (
    BackupConnectRequest,
    BackupHistoryResponse,
    BackupNewRepositoryRequest,
    BackupRefusal,
    BackupRepairRequest,
    BackupRepairResponse,
    BackupRestoreRequest,
    BackupSetUpRequest,
    BackupSnapshot,
    BackupSnapshotsResponse,
)

router = APIRouter(prefix="/api/backup", tags=["backup"])


@router.get("")
def backup_status(request: Request) -> BackupOverview:
    return app_state.backups(request).overview()


@router.get("/history")
def backup_history(request: Request) -> BackupHistoryResponse:
    return BackupHistoryResponse(runs=app_state.backups(request).history())


@router.get("/snapshots")
def backup_snapshots(request: Request) -> BackupSnapshotsResponse:
    """restic's snapshots, for the restore dialog: a run's history entry
    may be gone, and a snapshot made by hand has none."""
    backups = app_state.backups(request)
    return BackupSnapshotsResponse(
        workspace=str(app_state.workspace(request).root),
        snapshots=[
            BackupSnapshot(id=s.id, short_id=s.short_id, time=s.time, files=s.files, size=s.size)
            for s in reversed(backups.snapshots())
        ],
    )


@router.post("/restore", status_code=202)
def start_restore(request: Request, body: BackupRestoreRequest) -> BackupOverview:
    """Restore a snapshot into a new folder; 409 for the live workspace, a
    folder that holds files or a restore already running."""
    backups = app_state.backups(request)
    backups.start_restore(body.snapshot, Path(body.target))
    return backups.overview()


@router.post("/restore/stop")
def stop_restore(request: Request) -> BackupOverview:
    """Stop the restore, answering once it has."""
    backups = app_state.backups(request)
    backups.stop_restore()
    return backups.overview()


@router.post("/run", status_code=202)
def back_up_now(request: Request) -> BackupOverview:
    """Start a backup; 409 while another backup operation runs."""
    backups = app_state.backups(request)
    backups.run_now()
    return backups.overview()


_REFUSALS: dict[int | str, dict[str, Any]] = {
    409: {"model": BackupRefusal},
    412: {"model": BackupRefusal},
    422: {"model": BackupRefusal},
}


@router.post("/setup", status_code=202, response_model=BackupOverview, responses=_REFUSALS)
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
    return _answer(backups, lambda: backups.set_up(answers, expected_revision=body.revision))


@router.post("/repository", status_code=202, response_model=BackupOverview, responses=_REFUSALS)
def create_repository(
    request: Request, body: BackupNewRepositoryRequest
) -> BackupOverview | JSONResponse:
    """Create a new repository while the configured one is missing, save
    its folder, and start the first backup. Refuses a folder that holds
    files (409) and a missing or short password (422)."""
    backups = app_state.backups(request)
    answers = Replacement(Path(body.repository), body.password, body.revision)
    return _answer(backups, lambda: backups.create_repository(answers))


@router.post("/connect", response_model=BackupOverview, responses=_REFUSALS)
def connect_repository(
    request: Request, body: BackupConnectRequest
) -> BackupOverview | JSONResponse:
    """Copy an existing repository to local disk, check the password opens
    it, then use it; answers once it is connected. A wrong password or a
    folder that is not a repository is a 422, and nothing is saved."""
    backups = app_state.backups(request)
    answers = Replacement(Path(body.repository), body.password, body.revision)
    return _answer(backups, lambda: backups.connect(Path(body.source), answers))


def _answer(
    backups: BackupCoordinator, action: Callable[[], None]
) -> BackupOverview | JSONResponse:
    try:
        action()
    except StaleError as exc:
        return _refusal(412, "conflict", exc)
    except DestinationHoldsRepositoryError as exc:
        return _refusal(409, "conflict", exc, connect_from=str(exc.destination))
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
    *,
    connect_from: str | None = None,
) -> JSONResponse:
    """Set-up answers as a settings save does, with the field it refuses."""
    refusal = BackupRefusal(
        kind=kind, message=str(exc), field_errors=field_errors or {}, connect_from=connect_from
    )
    return JSONResponse(status_code=status, content=refusal.model_dump())
