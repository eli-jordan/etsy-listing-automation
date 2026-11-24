"""What the backup status says, and every warning it raises
(workspace-backup spec, *Status and warnings*; plan, PR 5).

Worked out afresh from the state file, the run history and restic's
snapshots on every read, so a warning clears as soon as its problem does and
there is nothing to dismiss. The server's status endpoint is the single
source for the Backup page, the banner and the nav icons (interactions,
*What the production implementation must finish*).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from etsy_listings.core.application.backup_restore import RestoreStatus
from etsy_listings.core.backup.destinations import ChangedFile
from etsy_listings.core.backup.repository import Snapshot
from etsy_listings.core.backup.state import BackupState, CheckResult, RunRecord
from etsy_listings.core.config.settings import BackupSettings, RetentionSettings

WARN_AFTER = timedelta(hours=24)
"""A last success, or a destination, this far behind warns (spec)."""
RETRY_AFTER = timedelta(hours=1)
"""A failed run is tried again this long after it ended, not at every check:
a repository that stays locked or unreadable would otherwise add a failed
run to the history every few minutes. Shorter than every offered interval."""

WarningKind = Literal["off", "repository_missing", "stale", "failed", "behind", "changed"]
KeptAs = Literal["recent", "weekly", "monthly"]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


class BackupWarning(_Model):
    kind: WarningKind
    message: str
    destination: str | None = None
    """The destination it is about, for ``behind`` and ``changed``."""
    banner: bool = True
    """Shown on every other page and as a dot on Admin; all but ``off``."""


class RunningBackup(_Model):
    """The operation in progress, for the running line."""

    operation: Literal["backup", "repair", "connect"]
    started_at: datetime
    step: str
    waiting_for: str | None = None
    """The job a backup waits for before it pauses the rest."""
    waiting_since: datetime | None = None
    files_done: int | None = None
    """Files read so far while backing up, or copied while copying."""
    files_total: int | None = None
    destination: str | None = None


class RepositoryOverview(_Model):
    path: str
    missing: bool
    """No restic repository at ``path``: backups stop (spec, *Missing repository*)."""
    problem: str | None = None
    """Why its snapshots could not be read, such as a wrong password."""
    password_stored: bool = False
    """Whether ``.env`` or the environment holds the password, so the
    missing-repository actions ask for one only when it does not."""
    snapshots: int = 0
    last_prune: datetime | None = None
    last_check: CheckResult | None = None


class DestinationOverview(_Model):
    path: str
    last_copy: datetime | None = None
    problem: str | None = None
    """Why the latest copy did not finish, such as an unreachable folder."""
    last_check: CheckResult | None = None
    changed: tuple[ChangedFile, ...] = ()
    unexpected: tuple[str, ...] = ()
    behind: bool = False


class BackupOverview(_Model):
    enabled: bool
    interval_hours: int | None = None
    last_success: datetime | None = None
    """The newest snapshot's time, from restic (spec, *Status and warnings*)."""
    next_due: datetime | None = None
    running: RunningBackup | None = None
    repository: RepositoryOverview | None = None
    destinations: list[DestinationOverview] = []
    warnings: list[BackupWarning] = []
    restore: RestoreStatus | None = None
    """The latest restore since the app started (spec, *Restore*)."""


@dataclass(frozen=True)
class RepositoryReading:
    """What was read from the repository for one overview."""

    missing: bool
    snapshots: tuple[Snapshot, ...] | None = None
    """Oldest first; None when they could not be read."""
    problem: str | None = None


def last_success(reading: RepositoryReading) -> datetime | None:
    return max((s.time for s in reading.snapshots or ()), default=None)


def next_due(
    settings: BackupSettings, success: datetime | None, runs: Sequence[RunRecord], now: datetime
) -> datetime:
    """``interval_hours`` after the last success, at once when there is
    none, and never sooner than :data:`RETRY_AFTER` after a failed run."""
    due = now if success is None else success + timedelta(hours=settings.interval_hours)
    latest = _latest_attempt(runs)
    failed_since = latest is not None and latest.outcome == "failed"
    if latest is not None and failed_since and (success is None or latest.started_at > success):
        due = max(due, latest.finished_at + RETRY_AFTER)
    return due


def _latest_attempt(runs: Sequence[RunRecord]) -> RunRecord | None:
    """The newest run that was not stopped by the app shutting down."""
    return next((run for run in reversed(runs) if run.outcome != "stopped"), None)


@dataclass(frozen=True)
class BackupFacts:
    """Everything an overview is worked out from."""

    settings: BackupSettings | None
    state: BackupState
    runs: Sequence[RunRecord]
    """This repository's runs, oldest first."""
    reading: RepositoryReading
    running: RunningBackup | None
    now: datetime
    password_stored: bool = False


def backup_overview(facts: BackupFacts) -> BackupOverview:
    settings, reading = facts.settings, facts.reading
    if settings is None:
        off = BackupWarning(kind="off", message="Backups are off.", banner=False)
        return BackupOverview(enabled=False, running=facts.running, warnings=[off])
    success = last_success(reading)
    destinations = [_destination(facts, path) for path in settings.destinations]
    return BackupOverview(
        enabled=True,
        interval_hours=settings.interval_hours,
        last_success=success,
        next_due=None if reading.missing else next_due(settings, success, facts.runs, facts.now),
        running=facts.running,
        repository=RepositoryOverview(
            path=str(settings.repository),
            missing=reading.missing,
            problem=reading.problem,
            password_stored=facts.password_stored,
            snapshots=len(reading.snapshots or ()),
            last_prune=facts.state.last_prune,
            last_check=facts.state.last_check,
        ),
        destinations=destinations,
        warnings=_warnings(settings.repository, facts, destinations),
    )


def _destination(facts: BackupFacts, path: Path) -> DestinationOverview:
    recorded = facts.state.destination(path)
    copied = recorded.last_copy
    snapshots = facts.reading.snapshots or ()
    # The oldest snapshot the destination has not had yet.
    pending = min((s.time for s in snapshots if copied is None or s.time > copied), default=None)
    return DestinationOverview(
        path=str(path),
        last_copy=copied,
        problem=recorded.problem,
        last_check=recorded.last_check,
        changed=recorded.changed,
        unexpected=recorded.unexpected,
        behind=pending is not None and facts.now - pending > WARN_AFTER,
    )


def _warnings(
    repository: Path, facts: BackupFacts, destinations: Sequence[DestinationOverview]
) -> list[BackupWarning]:
    if facts.reading.missing:
        return [
            BackupWarning(
                kind="repository_missing",
                message=f"Backup repository not found at {repository}. Backups have stopped.",
            )
        ]
    found: list[BackupWarning] = []
    success = last_success(facts.reading)
    if success is not None and facts.now - success > WARN_AFTER:
        found.append(BackupWarning(kind="stale", message="The last backup is more than a day old."))
    if (failure := _failure(facts)) is not None:
        found.append(BackupWarning(kind="failed", message=failure))
    for destination in destinations:
        found += _destination_warnings(destination)
    return found


def _destination_warnings(destination: DestinationOverview) -> list[BackupWarning]:
    found: list[BackupWarning] = []
    if destination.behind:
        reason = f" {destination.problem}" if destination.problem else ""
        message = f"{destination.path} is more than a day behind the backups.{reason}"
        found.append(BackupWarning(kind="behind", message=message, destination=destination.path))
    if destination.changed or destination.unexpected:
        message = destination.problem or (
            f"Something else changed files in {destination.path}. "
            "Repair it to set them aside and copy again."
        )
        found.append(BackupWarning(kind="changed", message=message, destination=destination.path))
    elif (check := destination.last_check) is not None and not check.ok and check.message:
        found.append(
            BackupWarning(kind="failed", message=check.message, destination=destination.path)
        )
    return found


def _failure(facts: BackupFacts) -> str | None:
    """restic's message for the last run, the last check, or the read that failed."""
    latest = _latest_attempt(facts.runs)
    check = facts.state.last_check
    if latest is not None and latest.outcome == "failed":
        return f"The last backup failed: {latest.message or 'no reason was given'}"
    if check is not None and not check.ok:
        return f"The last check of the backup storage folder failed: {check.message}"
    if facts.reading.problem is not None:
        return f"The backups could not be read: {facts.reading.problem}"
    return None


class HistoryEntry(_Model):
    run: RunRecord
    kept_as: KeptAs | None = None
    """The retention bucket holding the run's snapshot; None once it is
    forgotten, or for a run that made none."""


def history(
    runs: Sequence[RunRecord],
    snapshots: Sequence[Snapshot],
    retention: RetentionSettings,
    now: datetime,
) -> list[HistoryEntry]:
    """Every run, newest first, with the bucket its snapshot is kept in."""
    times = {s.id: s.time for s in snapshots}
    return [
        HistoryEntry(
            run=run, kept_as=_kept_as(times.get(run.snapshot_id or ""), times, retention, now)
        )
        for run in reversed(runs)
    ]


def _kept_as(
    time: datetime | None, times: dict[str, datetime], retention: RetentionSettings, now: datetime
) -> KeptAs | None:
    """The spec's wording of the retention (*Backup run* step 5): recent,
    else the latest of its week, else the latest of its month."""
    if time is None:
        return None
    if now - time <= timedelta(days=retention.keep_within_days):
        return "recent"
    if time == max(t for t in times.values() if t.isocalendar()[:2] == time.isocalendar()[:2]):
        return "weekly"
    return "monthly"
