from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer

from etsy_listings.cli import prompts
from etsy_listings.cli.options import RootOption, open_workspace
from etsy_listings.core.application.backup_provisioning import (
    NewRepository,
    PasswordSource,
    Provisioned,
    Provisioning,
    Source,
    provision,
    source_for,
)
from etsy_listings.core.application.backup_repository import (
    MIN_PASSWORD_LENGTH,
    BackupStatus,
    backup_settings,
    backup_status,
    configured_backup,
)
from etsy_listings.core.application.backup_restore import prepare_restore
from etsy_listings.core.application.backup_run import BackupProgress, BackupRunner
from etsy_listings.core.backup.binary import RESTIC_VERSION, ResticBinaries
from etsy_listings.core.backup.repository import RestoreProgress, Snapshot
from etsy_listings.core.config.secrets import BACKUP_PASSWORD_VAR
from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.userpath import to_native_path
from etsy_listings.core.workspace.workspace import Workspace

app = typer.Typer(no_args_is_help=True, help="Back up the workspace with restic.")

JsonOption = Annotated[bool, typer.Option("--json", help="Print the result as JSON.")]


@contextmanager
def _reported() -> Iterator[None]:
    try:
        yield
    except UserFacingError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    except prompts.Cancelled as exc:
        typer.echo("Cancelled; nothing was written.", err=True)
        raise typer.Exit(1) from exc


def _ask_password(source: Source) -> str:
    if not isinstance(source, NewRepository):
        return prompts.ask_text("Password of the existing backup:")
    password = prompts.ask_text(f"New backup password (at least {MIN_PASSWORD_LENGTH} characters):")
    if len(password) >= MIN_PASSWORD_LENGTH and password != prompts.ask_text(
        "Type the backup password again:"
    ):
        typer.echo("The two passwords did not match; nothing was written.", err=True)
        raise typer.Exit(1)
    return password


@app.command()
def init(root: RootOption = None) -> None:
    """Create the repository backup.repository names in settings.yaml, or,
    when a destination already holds a backup, copy that one there and use it.

    Uses the password in the workspace .env, or asks for one and stores it
    there. Downloads the pinned restic when no other is configured."""
    workspace = open_workspace(root)
    with _reported():
        saved = backup_settings(workspace)
        storage = saved.repository
        asked = Provisioning(
            storage=storage,
            source=source_for(saved.destinations),
            password=PasswordSource.stored_or(_ask_password),
        )

        def trying(source: Path | None) -> None:
            if source is None:
                typer.echo(f"Creating the backup repository at {storage}...", err=True)
            else:
                typer.echo(f"Copying the backup in {source} to {storage}...", err=True)

        done = provision(workspace, asked, binaries=ResticBinaries(), trying=trying)
    _report_init(workspace, storage, done)


def _report_init(workspace: Workspace, storage: Path, done: Provisioned) -> None:
    if done.connected is None:
        repository_id = done.repository_id or ""
        typer.echo(f"Created the backup repository at {storage} (id {repository_id[:8]}).")
    else:
        typer.echo(
            f"Connected to the backup in {done.connected.source}: "
            f"{len(done.connected.snapshots)} snapshots, copied to {storage}."
        )
    if done.workspace_id.notice is not None:
        typer.echo(done.workspace_id.notice)
    if done.stored_password:
        typer.echo(
            f"Stored the password in {workspace.root / layout.ENV_FILE} as "
            f"{BACKUP_PASSWORD_VAR}. Keep a copy in a password manager: the .env inside "
            "each backup is encrypted with it."
        )


_STEP_LINES = {
    "backing_up": "Backing up the workspace...",
    "forgetting": "Applying the retention...",
    "pruning": "Pruning unused data (weekly)...",
    "checking": "Checking the repository (weekly)...",
    "copying": "Copying to {destination}...",
    "checking_copy": "Checking the copy in {destination} (monthly)...",
}
PROGRESS_EVERY_SECONDS = 5.0


class _ProgressLines:
    def __init__(self) -> None:
        self._step: tuple[str, str | None] | None = None
        self._printed = 0.0

    def __call__(self, progress: BackupProgress) -> None:
        step = (progress.step, progress.destination)
        if step != self._step and progress.step in _STEP_LINES:
            self._step = step
            line = _STEP_LINES[progress.step].format(destination=progress.destination)
            typer.echo(line, err=True)
        elif progress.files_total and time.monotonic() - self._printed >= PROGRESS_EVERY_SECONDS:
            self._printed = time.monotonic()
            typer.echo(f"  {progress.files_done:,} of {progress.files_total:,} files", err=True)


@app.command()
def run(root: RootOption = None) -> None:
    """Back up the workspace now and apply the retention; prune and check the
    repository once a week. For when the app is stopped: it pauses no jobs
    in a running server."""
    workspace = open_workspace(root)
    with _reported():
        record = BackupRunner(workspace, ResticBinaries()).run(progress=_ProgressLines())
    for warning in record.warnings:
        typer.echo(f"Not backed up: {warning}", err=True)
    if record.notice is not None:
        typer.echo(record.notice)
    if record.snapshot_id is not None:
        typer.echo(f"Backed up {workspace.root} as snapshot {record.snapshot_id[:8]}.")
    for copy in record.copies:
        if copy.outcome == "copied":
            typer.echo(f"Copied to {copy.destination}.")
        else:
            typer.echo(f"Not copied to {copy.destination}: {copy.message}", err=True)
    if record.outcome != "succeeded":
        typer.echo(f"Backup {record.outcome}: {record.message}", err=True)
        raise typer.Exit(1)


@app.command()
def check(root: RootOption = None) -> None:
    """Check the backup repository's structure with restic check."""
    workspace = open_workspace(root)
    with _reported():
        result = BackupRunner(workspace, ResticBinaries()).check()
    if not result.ok:
        typer.echo(result.message, err=True)
        raise typer.Exit(1)
    typer.echo("The backup repository has no errors.")


def _snapshot_json(snapshot: Snapshot) -> dict[str, Any]:
    return {
        "id": snapshot.id,
        "short_id": snapshot.short_id,
        "time": snapshot.time.isoformat(),
        "paths": list(snapshot.paths),
        "hostname": snapshot.hostname,
        "files": snapshot.files,
        "size": snapshot.size,
    }


def _snapshot_line(snapshot: Snapshot) -> str:
    files = "" if snapshot.files is None else f"  {snapshot.files:,} files"
    size = "" if snapshot.size is None else f"  {snapshot.size / 2**20:,.1f} MiB"
    return f"{snapshot.short_id}  {snapshot.time:%Y-%m-%d %H:%M}{files}{size}"


@app.command()
def snapshots(root: RootOption = None, *, json_output: JsonOption = False) -> None:
    """List the repository's snapshots, oldest first."""
    workspace = open_workspace(root)
    with _reported():
        found = configured_backup(workspace, binaries=ResticBinaries()).open().snapshots()
    if json_output:
        typer.echo(json.dumps([_snapshot_json(snapshot) for snapshot in found], indent=2))
    elif not found:
        typer.echo("No snapshots yet.")
    else:
        for snapshot in found:
            typer.echo(_snapshot_line(snapshot))


class _RestoreLines:
    def __init__(self) -> None:
        self._printed = 0.0

    def __call__(self, figures: RestoreProgress) -> None:
        if time.monotonic() - self._printed < PROGRESS_EVERY_SECONDS:
            return
        self._printed = time.monotonic()
        typer.echo(restore_progress_line(figures), err=True)


def restore_progress_line(figures: RestoreProgress) -> str:
    """``  25% · 100 of 400 files``; restic's ``--json`` omits a zero ``files_restored``."""
    if not figures.files_total:
        return f"  {figures.percent:.0%}"
    return f"  {figures.percent:.0%} · {figures.files_done or 0:,} of {figures.files_total:,} files"


@app.command(name="restore")
def restore_command(
    snapshot: Annotated[str, typer.Argument(help="A snapshot id, its start, or latest.")],
    target: Annotated[str, typer.Argument(help="A new or empty folder to restore into.")],
    root: RootOption = None,
) -> None:
    """Restore a snapshot into a new folder, never over the workspace.

    Stopping it part way (Ctrl+C) leaves the files restored so far; delete
    them before restoring into that folder again."""
    workspace = open_workspace(root)
    folder = to_native_path(target).absolute()
    with _reported():
        prepared = prepare_restore(workspace, snapshot, folder, binaries=ResticBinaries())
        found = prepared.snapshot
        typer.echo(f"Restoring snapshot {found.short_id} into {prepared.target}...", err=True)
        figures = prepared.run(progress=_RestoreLines())
    files = f"{figures.files_done:,} files" if figures.files_done is not None else "the files"
    typer.echo(f"Restored {files} from {found.time:%Y-%m-%d %H:%M} into {prepared.target}.")


def _status_json(status: BackupStatus) -> dict[str, Any]:
    settings = status.settings
    if settings is None:
        return {"enabled": False}
    latest = status.snapshots[-1].time.isoformat() if status.snapshots else None
    return {
        "enabled": True,
        "repository": str(settings.repository),
        "destinations": [str(path) for path in settings.destinations],
        "interval_hours": settings.interval_hours,
        "retention": settings.retention.model_dump(),
        "restic": None if status.binary is None else str(status.binary),
        "snapshots": None if status.snapshots is None else len(status.snapshots),
        "latest_snapshot": latest,
        "problem": status.problem,
    }


def _status_lines(status: BackupStatus) -> list[str]:
    settings = status.settings
    assert settings is not None
    retention = settings.retention
    lines = [
        f"Repository:   {settings.repository}",
        *(f"Destination:  {path}" for path in settings.destinations),
        f"Schedule:     every {settings.interval_hours} hours",
        f"Retention:    every snapshot for {retention.keep_within_days} days, then "
        f"{retention.weekly} weekly and {retention.monthly} monthly",
        f"restic:       {status.binary or f'not installed (pinned {RESTIC_VERSION})'}",
    ]
    if status.snapshots is not None:
        latest = f", latest {status.snapshots[-1].time:%Y-%m-%d %H:%M}" if status.snapshots else ""
        lines.append(f"Reachable:    {len(status.snapshots)} snapshots{latest}")
    return lines


@app.command()
def status(root: RootOption = None, *, json_output: JsonOption = False) -> None:
    """Show the backup configuration and whether the repository opens.

    Exits 1 when backups are configured but the repository cannot be read."""
    workspace = open_workspace(root)
    with _reported():
        report = backup_status(workspace, binaries=ResticBinaries())
    if json_output:
        typer.echo(json.dumps(_status_json(report), indent=2))
    elif report.settings is None:
        typer.echo(f"Backups are off: {workspace.settings_file()} has no backup: block.")
    else:
        for line in _status_lines(report):
            typer.echo(line)
        if report.problem is not None:
            typer.echo(report.problem, err=True)
    if report.problem is not None:
        raise typer.Exit(1)
