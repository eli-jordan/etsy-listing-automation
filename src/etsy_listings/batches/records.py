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
from contextlib import ExitStack, contextmanager
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
    ignored: list[str] = Field(default_factory=list)
    """A ZIP's files that are not PNGs, by their path in it: counted and
    listed on the staging page, never rows (spec, *Accepted input*)."""

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

AiState = Literal["queued", "running", "done", "failed", "stopped", "cancelled"]
"""Where a created row's AI work is (A40), set by the batch queue.
``stopped`` is a queued row **Cancel batch** took out of the queue;
``cancelled`` is a run that was stopped part-way. **Resume** queues both
again."""


class AiStep(BaseModel):
    """One node of the row's last run as it ended -- the editor's
    ``WorkflowStep``, kept here so a failed row still shows where it failed
    after the server that ran it has gone."""

    id: str
    state: str
    detail: str | None = None


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
    (A39). The listing's name, except where the row's bytes were already in
    ``designs/`` and the listing reuses that file (spec, *Content
    deduplication*)."""
    creation: Creation = "pending"
    claimed: bool = False
    """A39's recorded step: set before ``listings/<name>/`` is made, so a
    directory found there on resume -- with no ``listing.yaml`` yet -- is
    known to be this row's own."""
    error: str | None = None
    ai: AiState | None = None
    """``None`` until the listing exists; creating it queues it (spec,
    *Confirming a batch*: only created rows enter the AI queue)."""
    ai_error: str | None = None
    ai_steps: list[AiStep] = Field(default_factory=list)
    reviewed: bool = False
    """The seller's own judgement (spec, *Review workflow*): set and cleared
    only by Mark reviewed / Mark needs review, never by an edit, a proposal
    or a deploy, and never read by ``plan`` or ``apply``."""
    deleted: bool = False
    """The listing was deleted (A42). The row stays, struck through, so the
    batch still says what it made (UI doc §7); nothing follows or queues it
    again."""


DRAFTING: frozenset[AiState | None] = frozenset({"queued", "running"})


def has_listing(row: BatchRow) -> bool:
    """Does the row have a listing the seller can open? Created, and not
    deleted since."""
    return row.creation == "created" and not row.deleted


def reviewable(row: BatchRow) -> bool:
    """May the seller mark this row reviewed, or back? Only a listing they
    can look at: not one still queued or drafting, deleted, or never created
    (UI doc §7)."""
    return has_listing(row) and row.ai not in DRAFTING


class NotReviewable(ValueError):
    """Mark reviewed on a row :func:`reviewable` refuses."""


class Batch(_Record):
    created_at: datetime
    rows: list[BatchRow]


class _Store[R: _Record]:
    """Load and save one kind of record, with a lock per record for the
    read-modify-write every mutation is (A37)."""

    def __init__(
        self,
        workspace: Workspace,
        model: type[R],
        file: Callable[[str], Path],
        ids: Callable[[], list[str]],
    ) -> None:
        self._workspace = workspace
        self._model = model
        self._file = file
        self._ids = ids
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

    def rename_listing_template(self, old: str, new: str) -> None:
        """A listing template renamed: every record made from ``old`` now
        says ``new``, each under its own lock. Only the name moves -- the
        frozen ``template`` document and its files are the record's own
        snapshot and stay as they were (spec, *Frozen staging*), and the
        label is the seller's. The name is what the Listing templates card
        counts batches by and the staging page shows, so without this a
        rename silently cut a template off from its batches."""
        for record_id in self._ids():
            with self.lock(record_id):
                record = self.load(record_id)
                if record is not None and record.listing_template == old:
                    self.save(record.model_copy(update={"listing_template": new}))


class StagingStore(_Store[StagingSession]):
    def __init__(self, workspace: Workspace) -> None:
        super().__init__(
            workspace, StagingSession, workspace.staging_session_file, workspace.staging_ids
        )

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
        super().__init__(workspace, Batch, workspace.batch_file, workspace.batch_ids)

    def all(self) -> list[Batch]:
        return [batch for id_ in self._workspace.batch_ids() if (batch := self.load(id_))]

    def remove(self, batch: str) -> None:
        """Delete batch record (spec, *Cancellation and deletion*): the
        record and the directory beside it -- the frozen template and any
        kept upload. Nothing outside ``.cache/batches/`` is touched."""
        self._file(batch).unlink(missing_ok=True)
        directory = self._workspace.batch_dir(batch)
        if directory.is_dir():
            remove_tree(directory)

    def review(self, batch_id: str, row_id: str, *, reviewed: bool) -> Batch:
        """Mark reviewed / Mark needs review (spec, *Review workflow*).
        :class:`KeyError` for a batch or row nobody holds,
        :class:`NotReviewable` for a row with no listing to look at yet."""
        with self.lock(batch_id):
            batch = self.load(batch_id)
            rows = batch.rows if batch is not None else []
            index = next((i for i, row in enumerate(rows) if row.id == row_id), None)
            if batch is None or index is None:
                raise KeyError(row_id)
            if not reviewable(rows[index]):
                raise NotReviewable(rows[index].name)
            rows[index] = rows[index].model_copy(update={"reviewed": reviewed})
            self.save(batch)
            return batch

    # A42: a row names its listing by its current name, exactly as a
    # proposal record does -- two listings differing only in case can
    # coexist on a case-sensitive filesystem, and one's rename or delete
    # must not reach the other's row. A deleted row is not followed: a new
    # listing given its old name is not its listing.

    def rename_listing(self, old: str, new: str) -> None:
        """Rename's half of A42: every batch's row for ``old`` now names
        ``new``. Its design target is the design's file, which stays."""
        with self.following_rename(old, new):
            pass

    @contextmanager
    def following_rename(self, old: str, new: str) -> Iterator[None]:
        """:meth:`rename_listing` around the move itself: every batch's lock
        is held while the body moves the listing, and the rows follow only
        if it returns. The listings API takes these **before** its listing
        write locks, the order creating a row takes them in (a batch's lock,
        then its row's name), so a rename and a Retry creating a row of the
        same name cannot each wait on the other. No row names ``old`` while
        the move is half done, so the queue cannot start one in between."""
        ids = sorted(self._workspace.batch_ids())
        with ExitStack() as held:
            for batch_id in ids:
                held.enter_context(self.lock(batch_id))
            yield
            for batch_id in ids:
                self._change_rows(
                    batch_id,
                    lambda row: row.name == old and not row.deleted,
                    lambda _: {"name": new},
                )

    def mark_deleted(self, listing: str) -> None:
        """Delete's half of A42: the row stays, marked deleted, and leaves
        the queue. A row still queued is cancelled here; a running one is
        the delete's to stop, and its run's end records ``cancelled``."""
        self._each_row(
            lambda row: row.name == listing and has_listing(row),
            lambda row: {"deleted": True} | ({"ai": "cancelled"} if row.ai == "queued" else {}),
        )

    def restore_listing(self, listing: str, design: str | None) -> None:
        """A pending delete cancelled (PRD 63's Cancel clears ``lifecycle:
        deleted`` before apply): the listing never went, so its rows are no
        longer deleted. Only a row whose design target is the listing's
        design (``design``, its ``design.default`` ref) comes back -- a row
        for an earlier listing wiped under the same name is not this one's.
        The AI state stays as the delete left it; Resume queues a
        ``cancelled`` row again."""
        self._each_row(
            lambda row: (
                row.deleted
                and row.name == listing
                and self._workspace.design_ref(row.design) == design
            ),
            lambda _: {"deleted": False},
        )

    def _each_row(
        self,
        which: Callable[[BatchRow], bool],
        change: Callable[[BatchRow], dict[str, object]],
    ) -> None:
        for batch_id in self._workspace.batch_ids():
            with self.lock(batch_id):
                self._change_rows(batch_id, which, change)

    def _change_rows(
        self,
        batch_id: str,
        which: Callable[[BatchRow], bool],
        change: Callable[[BatchRow], dict[str, object]],
    ) -> None:
        """Under ``batch_id``'s lock, which the caller holds."""
        batch = self.load(batch_id)
        if batch is None or not any(which(row) for row in batch.rows):
            return
        batch.rows[:] = [
            row.model_copy(update=change(row)) if which(row) else row for row in batch.rows
        ]
        self.save(batch)
