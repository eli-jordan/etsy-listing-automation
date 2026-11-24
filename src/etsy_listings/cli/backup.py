"""``etsy-listings backup``: the workspace's restic repository from a terminal
(workspace-backup spec, *CLI*).

``init``, ``run``, ``check``, ``snapshots``, ``status`` and ``restore``.
The CLI does not coordinate with a running server, so ``run`` pauses no
jobs; restic's own repository lock keeps two processes apart.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer

from etsy_listings.cli import prompts
from etsy_listings.cli.options import open_workspace, root_option
from etsy_listings.core.application import credentials
from etsy_listings.core.application.backup_missing import (
    Connected,
    connect_existing,
    existing_copies,
)
from etsy_listings.core.application.backup_repository import (
    MIN_PASSWORD_LENGTH,
    BackupStatus,
    ConfiguredBackup,
    backup_status,
    configured_backup,
    create_repository,
    ensure_workspace_id,
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
    """A user-facing failure is its message and exit status 1."""
    try:
        yield
    except UserFacingError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    except prompts.Cancelled as exc:
        typer.echo("Cancelled; nothing was written.", err=True)
        raise typer.Exit(1) from exc


def _ask_password() -> str:
    password = prompts.ask_text(f"New backup password (at least {MIN_PASSWORD_LENGTH} characters):")
    if len(password) >= MIN_PASSWORD_LENGTH and password != prompts.ask_text(
        "Type the backup password again:"
    ):
        typer.echo("The two passwords did not match; nothing was written.", err=True)
        raise typer.Exit(1)
    return password


@app.command()
def init(root: str | None = root_option()) -> None:
    """Create the repository backup.repository names in settings.yaml, or,
    when a destination already holds a backup, copy that one there and use it.

    Uses the password in the workspace .env, or asks for one and stores it
    there first. Downloads the pinned restic when no other is configured."""
    workspace = open_workspace(root)
    with _reported():
        backup = configured_backup(workspace, binaries=ResticBinaries())
        copies = existing_copies(backup.destinations)
        if copies:
            connected = _connect(backup, copies)
            _workspace_id(workspace, connected.snapshots)
            return
        existing = backup.password
        password = existing or _ask_password()
        typer.echo(f"Creating the backup repository at {backup.storage}...", err=True)
        repository_id = create_repository(backup, password, store=existing is None)
        _workspace_id(workspace, ())
    typer.echo(f"Created the backup repository at {backup.storage} (id {repository_id[:8]}).")
    if existing is None:
        _stored(backup)


def _workspace_id(workspace: Workspace, snapshots: Sequence[Snapshot]) -> None:
    """Keep the block's workspace ID, or write the one ``snapshots`` carry."""
    chosen = ensure_workspace_id(workspace, snapshots)
    if chosen.notice is not None:
        typer.echo(chosen.notice)


def _connect(backup: ConfiguredBackup, copies: tuple[Path, ...]) -> Connected:
    """``init`` with a destination that is already a backup: connect it."""
    existing = backup.password
    password = existing or prompts.ask_text("Password of the existing backup:")

    def trying(source: Path) -> None:
        typer.echo(f"Copying the backup in {source} to {backup.storage}...", err=True)

    env_file = backup.env_file if existing is not None else None
    connected = connect_existing(backup, copies, password, env_file=env_file, trying=trying)
    if existing is None:
        credentials.store(backup.workspace, credentials.BACKUP_PASSWORD, (password,))
    typer.echo(
        f"Connected to the backup in {connected.source}: {len(connected.snapshots)} snapshots, "
        f"copied to {backup.storage}."
    )
    if existing is None:
        _stored(backup)
    return connected


def _stored(backup: ConfiguredBackup) -> None:
    typer.echo(
        f"Stored the password in {backup.workspace / layout.ENV_FILE} as "
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
    """Each step once per destination, and the files read at most every few
    seconds."""

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
def run(root: str | None = root_option()) -> None:
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
def check(root: str | None = root_option()) -> None:
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
def snapshots(root: str | None = root_option(), *, json_output: JsonOption = False) -> None:
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
    """The percentage and files at most every few seconds."""

    def __init__(self) -> None:
        self._printed = 0.0

    def __call__(self, figures: RestoreProgress) -> None:
        if time.monotonic() - self._printed < PROGRESS_EVERY_SECONDS:
            return
        self._printed = time.monotonic()
        typer.echo(restore_progress_line(figures), err=True)


def restore_progress_line(figures: RestoreProgress) -> str:
    """``  25% · 100 of 400 files``. restic's ``--json`` leaves out a zero
    ``files_restored``, so a missing count is none yet."""
    if not figures.files_total:
        return f"  {figures.percent:.0%}"
    return f"  {figures.percent:.0%} · {figures.files_done or 0:,} of {figures.files_total:,} files"


@app.command(name="restore")
def restore_command(
    snapshot: Annotated[str, typer.Argument(help="A snapshot id, its start, or latest.")],
    target: Annotated[str, typer.Argument(help="A new or empty folder to restore into.")],
    root: str | None = root_option(),
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
def status(root: str | None = root_option(), *, json_output: JsonOption = False) -> None:
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
