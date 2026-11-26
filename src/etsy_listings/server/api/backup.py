"""The backup status, history, Back up now, set-up, repair, restore, and the
missing-repository actions.

``GET /api/backup`` is the one status source for the Backup page, the banner
on every other page and both nav icons. Setup's edits are not here: they save
through ``PATCH /api/admin/settings`` and its revision check.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from etsy_listings.core.application import backup_setup
from etsy_listings.core.application.backup_coordinator import BackupCoordinator
from etsy_listings.core.application.backup_missing import Replacement
from etsy_listings.core.application.backup_overview import BackupOverview
from etsy_listings.core.application.backup_provisioning import DestinationHoldsRepositoryError
from etsy_listings.core.application.backup_restore import default_target
from etsy_listings.core.application.refusals import InvalidSettingsEditError
from etsy_listings.core.errors import ConflictError, RefusedError, StaleError
from etsy_listings.core.workspace.userpath import to_native_path
from etsy_listings.server.api import app_state
from etsy_listings.server.api.refusal_status import refusal_status
from etsy_listings.server.api.schemas import (
    BackupConnected,
    BackupConnectRequest,
    BackupHistoryResponse,
    BackupNewRepositoryRequest,
    BackupRefusal,
    BackupRepairRequest,
    BackupRepairResponse,
    BackupRestoreRequest,
    BackupSetUpRequest,
    BackupSetUpResponse,
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
    workspace = app_state.workspace(request).root
    return BackupSnapshotsResponse(
        workspace=str(workspace),
        snapshots=[
            BackupSnapshot(
                id=s.id,
                short_id=s.short_id,
                time=s.time,
                files=s.files,
                size=s.size,
                restore_target=str(default_target(workspace, s)),
            )
            for s in reversed(backups.snapshots())
        ],
    )


@router.post("/restore", status_code=202)
def start_restore(request: Request, body: BackupRestoreRequest) -> BackupOverview:
    """Restore a snapshot into a new folder; 409 for the live workspace, a
    folder that holds files or a restore already running."""
    backups = app_state.backups(request)
    backups.start_restore(body.snapshot, to_native_path(body.target))
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


@router.post("/setup", status_code=202, response_model=BackupSetUpResponse, responses=_REFUSALS)
def set_up(request: Request, body: BackupSetUpRequest) -> BackupSetUpResponse | JSONResponse:
    """Write the ``backup:`` block and the password, create the repository
    and the destination folders, then start the first backup. Refuses a
    short password (422), a folder that holds files (409) and a destination
    whose parent is missing (422), writing nothing.

    When a destination already holds a backup, connects it instead, as
    ``/connect`` does, answering once it is copied: ``connected`` names the
    destination. Refuses a password that does not open it (422, field
    ``password``), part of a copy, and two different repositories (422)."""
    backups = app_state.backups(request)
    answers = backup_setup.BackupSetUp(
        repository=to_native_path(body.repository),
        destinations=tuple(to_native_path(path) for path in body.destinations),
        interval_hours=body.interval_hours,
        retention=body.retention,
        password=body.password,
    )
    connected: list[BackupConnected] = []

    def run() -> None:
        found = backups.set_up(answers, expected_revision=body.revision)
        if found is not None:
            connected.append(
                BackupConnected(
                    destination=str(found.source),
                    snapshots=len(found.snapshots),
                    notice=found.notice,
                )
            )

    answer = _answer(backups, run)
    if isinstance(answer, JSONResponse):
        return answer
    found = connected[0] if connected else None
    return BackupSetUpResponse.model_validate(answer.model_dump() | {"connected": found})


@router.post("/repository", status_code=202, response_model=BackupOverview, responses=_REFUSALS)
def create_repository(
    request: Request, body: BackupNewRepositoryRequest
) -> BackupOverview | JSONResponse:
    """Create a new repository while the configured one is missing, save
    its folder, and start the first backup. Refuses a folder that holds
    files (409) and a missing or short password (422)."""
    backups = app_state.backups(request)
    answers = Replacement(to_native_path(body.repository), body.password, body.revision)
    return _answer(backups, lambda: backups.create_repository(answers))


@router.post("/connect", response_model=BackupOverview, responses=_REFUSALS)
def connect_repository(
    request: Request, body: BackupConnectRequest
) -> BackupOverview | JSONResponse:
    """Copy an existing repository to local disk, check the password opens
    it, then use it; answers once it is connected. A wrong password or a
    folder that is not a repository is a 422, and nothing is saved."""
    backups = app_state.backups(request)
    answers = Replacement(to_native_path(body.repository), body.password, body.revision)
    return _answer(backups, lambda: backups.connect(to_native_path(body.source), answers))


def _answer(
    backups: BackupCoordinator, action: Callable[[], None]
) -> BackupOverview | JSONResponse:
    try:
        action()
    except (StaleError, ConflictError, RefusedError) as exc:
        return _refusal(exc)
    return backups.overview()


@router.post("/repair")
def repair(request: Request, body: BackupRepairRequest) -> BackupRepairResponse:
    """Set aside a destination's changed and unexpected files and copy it
    again (spec, *Changed and unexpected files*). Answers when it ends."""
    result = app_state.backups(request).repair(to_native_path(body.destination))
    return BackupRepairResponse(
        set_aside=None if result.set_aside is None else str(result.set_aside),
        moved=list(result.moved),
        outcome=result.copy.outcome,
        message=result.copy.message,
    )


_REFUSAL_KINDS: dict[type[Exception], Literal["stale", "conflict", "invalid"]] = {
    StaleError: "stale",
    ConflictError: "conflict",
    RefusedError: "invalid",
}


def _refusal(exc: StaleError | ConflictError | RefusedError) -> JSONResponse:
    kind = next(kind for category, kind in _REFUSAL_KINDS.items() if isinstance(exc, category))
    refusal = BackupRefusal(
        kind=kind,
        message=str(exc),
        field_errors=exc.field_errors if isinstance(exc, InvalidSettingsEditError) else {},
        connect_from=(
            str(exc.destination) if isinstance(exc, DestinationHoldsRepositoryError) else None
        ),
    )
    return JSONResponse(status_code=refusal_status(exc), content=refusal.model_dump())
