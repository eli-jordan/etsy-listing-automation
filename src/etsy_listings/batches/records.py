"""The two cache records batch creation keeps, and the stores over them (A37).

A **staging session** is ``.cache/staging/<id>/session.json``: the frozen
listing template, one row per unique upload, and the names the seller typed.
A **batch** is ``.cache/batches/<id>.json``: the same frozen template and one
row per listing it creates, with each row's allocated name and creation state
(A39). Both are schema-versioned JSON written atomically, and a record whose
``schema`` this code does not know -- or that will not parse -- is treated as
absent: this is cache, and a record nobody can read is one nobody lost.

A batch keeps its staging session's id. Confirming twice therefore finds the
batch the first confirm wrote instead of making a second (A39), and the id is
as opaque as a fresh one would be.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from etsy_listings.workspace.atomic import write_json_atomic
from etsy_listings.workspace.workspace import Workspace, remove_tree

SCHEMA = 1

STAGING_LIFETIME = timedelta(days=7)
"""A46: a staging session expires seven days after its last edit."""


class _Record(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_version: int = Field(SCHEMA, alias="schema")
    id: str
    listing_template: str
    template: dict[str, Any]
    """The listing template's document as it was when staging began (spec,
    *Frozen staging*). Its owned files are frozen beside the record."""
    template_saved_at: datetime
    label: str


class StagingRow(BaseModel):
    """One unique design: every upload with these bytes, the name its row
    has, and the design check's refusal if it will not print."""

    id: str
    sha256: str
    sources: list[str]
    base: str
    """The name the review starts from: the first source's stem through
    `slugify`, or what the seller typed."""
    typed: bool = False
    """A typed name is flagged when it is taken, never changed (A38)."""
    error: str | None = None


class StagingSession(_Record):
    created_at: datetime
    updated_at: datetime
    rows: list[StagingRow]

    @property
    def expires_at(self) -> datetime:
        return self.updated_at + STAGING_LIFETIME

    def _row_index(self, row: str) -> int:
        for index, candidate in enumerate(self.rows):
            if candidate.id == row:
                return index
        raise KeyError(row)

    def renamed(self, row: str, name: str, *, now: datetime) -> Self:
        rows = list(self.rows)
        index = self._row_index(row)
        rows[index] = rows[index].model_copy(update={"base": name.strip(), "typed": True})
        return self.model_copy(update={"rows": rows, "updated_at": now})

    def removed(self, row: str, *, now: datetime) -> Self:
        index = self._row_index(row)
        rows = [*self.rows[:index], *self.rows[index + 1 :]]
        return self.model_copy(update={"rows": rows, "updated_at": now})

    def relabelled(self, label: str, *, now: datetime) -> Self:
        return self.model_copy(update={"label": label, "updated_at": now})


Creation = Literal["pending", "created", "failed"]


class BatchRow(BaseModel):
    id: str
    sha256: str
    sources: list[str]
    base: str
    """What a re-allocation suffixes, so a second clash gives ``-3`` rather
    than ``-2-2``."""
    name: str
    design: str
    """The design's stem under ``designs/``, the row's *design target*
    (A39). The listing's name today; a reused design (PR 7) is where the two
    part."""
    creation: Creation = "pending"
    claimed: bool = False
    """A39's recorded step: set before ``listings/<name>/`` is made, so a
    directory found there on resume -- with no ``listing.yaml`` yet -- is
    known to be this row's own."""
    error: str | None = None


class Batch(_Record):
    created_at: datetime
    rows: list[BatchRow]


class _Store[R: _Record]:
    """Load and save one kind of record, with a lock per record for the
    read-modify-write every mutation is (A37)."""

    def __init__(self, workspace: Workspace, model: type[R], file: Callable[[str], Path]) -> None:
        self._workspace = workspace
        self._model = model
        self._file = file
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    @contextmanager
    def lock(self, record: str) -> Iterator[None]:
        with self._guard:
            lock = self._locks.setdefault(record, threading.Lock())
        with lock:
            yield

    def load(self, record: str) -> R | None:
        path = self._file(record)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
            return None
        try:
            return self._model.model_validate(raw)
        except ValidationError:
            return None

    def save(self, record: R) -> None:
        write_json_atomic(self._file(record.id), record.model_dump(mode="json", by_alias=True))


class StagingStore(_Store[StagingSession]):
    def __init__(self, workspace: Workspace) -> None:
        super().__init__(workspace, StagingSession, workspace.staging_session_file)

    def remove(self, session: str) -> None:
        directory = self._workspace.staging_dir(session)
        if directory.is_dir():
            remove_tree(directory)

    def sweep(self, *, now: datetime) -> None:
        """A46: drop every session seven days past its last edit. A directory
        with no readable record is judged by its own age instead -- it is a
        staging still being written, or one a crash or a schema change left
        behind."""
        for session in self._workspace.staging_ids():
            record = self.load(session)
            if record is not None:
                expired = record.expires_at < now
            else:
                modified = self._workspace.staging_dir(session).stat().st_mtime
                expired = datetime.fromtimestamp(modified, tz=now.tzinfo) + STAGING_LIFETIME < now
            if expired:
                with self.lock(session):
                    self.remove(session)


class BatchStore(_Store[Batch]):
    def __init__(self, workspace: Workspace) -> None:
        super().__init__(workspace, Batch, workspace.batch_file)

    def all(self) -> list[Batch]:
        return [batch for id_ in self._workspace.batch_ids() if (batch := self.load(id_))]
