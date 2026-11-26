from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from etsy_listings.core.backup.destinations import ChangedFile, CopyOutcome
from etsy_listings.core.user_directory import user_directory
from etsy_listings.core.workspace.atomic import write_json_atomic

STATE_FILE = "backup-state.json"
HISTORY_FILE = "backup-history.jsonl"

RunOutcome = Literal["succeeded", "failed", "stopped"]


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", use_attribute_docstrings=True)


class CheckResult(_Record):
    at: datetime
    ok: bool
    message: str | None = None
    """restic's message when the check failed."""


class DestinationState(_Record):
    last_copy: datetime | None = None
    """The last copy that finished."""
    problem: str | None = None
    """Why the latest copy did not finish; None once one does."""
    last_check: CheckResult | None = None
    changed: tuple[ChangedFile, ...] = ()
    """Found by the latest copy or check; kept until a repair."""
    unexpected: tuple[str, ...] = ()


class BackupState(_Record):
    repository: str
    last_prune: datetime | None = None
    last_check: CheckResult | None = None
    destinations: dict[str, DestinationState] = {}
    """Keyed by the destination's path as ``settings.yaml`` gives it."""

    def destination(self, path: Path) -> DestinationState:
        return self.destinations.get(str(path), DestinationState())

    def with_destination(self, path: Path, state: DestinationState) -> BackupState:
        return self.model_copy(update={"destinations": {**self.destinations, str(path): state}})


class CopyRecord(_Record):
    destination: str
    outcome: CopyOutcome
    message: str | None = None


class RunRecord(_Record):
    """One run's outcome, as the history keeps it."""

    repository: str
    started_at: datetime
    finished_at: datetime
    outcome: RunOutcome
    snapshot_id: str | None = None
    """Set once restic made a snapshot, even when a later step failed."""
    failed_step: str | None = None
    message: str | None = None
    warnings: tuple[str, ...] = ()
    """Files restic could not read; the snapshot was made without them."""
    data_added: int | None = None
    """Bytes the snapshot added to the repository, from restic's summary."""
    copies: tuple[CopyRecord, ...] = ()
    """Each destination's copy, in the configured order."""
    notice: str | None = None
    """Something the run decided that the seller should know, such as a
    new workspace ID beside several others."""


class BackupStateStore:
    def __init__(self, home: Path | None = None) -> None:
        self.directory = user_directory(home)

    def load(self, repository: Path) -> BackupState:
        fresh = BackupState(repository=str(repository))
        try:
            state = BackupState.model_validate_json(self._path(STATE_FILE).read_bytes())
        except (OSError, ValidationError):
            return fresh
        return state if state.repository == fresh.repository else fresh

    def save(self, state: BackupState) -> None:
        write_json_atomic(self._path(STATE_FILE), state.model_dump(mode="json"))

    def append_run(self, record: RunRecord) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        with self._path(HISTORY_FILE).open("a+b") as history:
            prefix = b""
            if history.tell():
                history.seek(-1, os.SEEK_END)
                if history.read(1) != b"\n":
                    prefix = b"\n"
            line = json.dumps(record.model_dump(mode="json")).encode("utf-8")
            history.write(prefix + line + b"\n")

    def runs(self) -> list[RunRecord]:
        return list(self._runs())

    def _runs(self) -> Iterator[RunRecord]:
        try:
            lines = self._path(HISTORY_FILE).read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return
        for line in lines:
            with contextlib.suppress(ValidationError):
                yield RunRecord.model_validate_json(line)

    def _path(self, name: str) -> Path:
        return self.directory / name
