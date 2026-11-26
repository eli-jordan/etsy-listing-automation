from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from etsy_listings.core.config.template_refs import rename_template_refs
from etsy_listings.core.workspace.atomic import read_bytes_retrying, write_json_atomic
from etsy_listings.core.workspace.trees import remove_tree
from etsy_listings.core.workspace.workspace import Workspace

SCHEMA = 1

STAGING_LIFETIME = timedelta(days=7)
"""staging expiry: a staging session expires seven days after its last edit."""


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
    id: str
    sha256: str
    sources: list[str]
    base: str
    """The name the review starts from: the first source's stem through
    `slugify`, or what the seller typed."""
    typed: bool = False
    """A typed name is flagged when it is taken, never changed."""
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

AiState = Literal[
    "queued", "running", "done", "failed", "stopped", "cancelled", "cancelled_by_deploy"
]
"""Where a created row's AI work is, set by the batch queue.
``stopped`` is a queued row **Cancel batch** took out of the queue;
``cancelled`` is a run that was stopped part-way. **Resume** queues both
again. ``cancelled_by_deploy`` is work a UI deploy of the listing cancelled,
queued or running: Resume leaves it, so no proposal lands on a listing
after its deploy, and only the row's own Retry queues it again."""

RETRYABLE: frozenset[AiState] = frozenset({"failed", "stopped", "cancelled", "cancelled_by_deploy"})
"""The AI states a row's own **Retry** queues again (UI doc §7): a failed, stopped
or cancelled run, and work a deploy cancelled. Here rather than with the
queue because Retry's choice -- recreate, requeue or refuse -- is decided
before the queue is asked (module-structure plan, PR 7)."""


class AiStep(BaseModel):
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
    """The design's stem under ``designs/``, the row's *design target*.
    The listing's name, except where the row's bytes were already in
    ``designs/`` and the listing reuses that file (spec, *Content
    deduplication*)."""
    creation: Creation = "pending"
    claimed: bool = False
    """recorded step: set before ``listings/<name>/`` is made, so a
    directory found there on resume -- with no ``listing.yaml`` yet -- is
    known to be this row's own."""
    error: str | None = None
    ai: AiState | None = None
    """``None`` until the listing exists; creating it queues it (spec,
    *Confirming a batch*: only created rows enter the AI queue)."""
    ai_error: str | None = None
    ai_steps: list[AiStep] = Field(default_factory=list)
    reviewed: bool = False
    """The seller's judgement (spec, *Review workflow*): set and cleared by
    Mark reviewed / Mark needs review, and set by a full apply of the
    listing, since deploying it is that judgement made
    (:meth:`BatchStore.mark_deployed`). Never set by an edit or a proposal,
    never cleared by anything but Mark needs review, and never read by
    ``plan`` or ``apply``."""
    deleted: bool = False
    """The listing was deleted. The row stays, struck through, so the
    batch still says what it made (UI doc §7); nothing follows or queues it
    again."""


DRAFTING: frozenset[AiState | None] = frozenset({"queued", "running"})


def has_listing(row: BatchRow) -> bool:
    return row.creation == "created" and not row.deleted


def reviewable(row: BatchRow) -> bool:
    return has_listing(row) and row.ai not in DRAFTING


class NotReviewableError(ValueError): ...


class Batch(_Record):
    created_at: datetime
    rows: list[BatchRow]


_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}


class _Store[R: _Record]:
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

    @property
    def workspace(self) -> Workspace:
        return self._workspace

    @contextmanager
    def lock(self, record: str) -> Iterator[None]:
        # Shared by every store over this file (the UI server's, an apply's
        # mark_deployed); like core/workspace/locks.py's, it does not reach a second process.
        key = str(self._file(record).absolute()).casefold()
        with _GUARD:
            lock = _LOCKS.setdefault(key, threading.Lock())
        with lock:
            yield

    def load(self, record: str) -> R | None:
        path = self._file(record)
        try:
            raw = json.loads(read_bytes_retrying(path).decode("utf-8"))
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

    def rename_mockup_template(self, old: str, new: str) -> None:
        """A mockup template renamed: frozen documents naming ``old`` now say
        ``new``. Unlike a listing template's rename this does touch the frozen
        copy, because that copy points at a directory it does not own, and
        confirming or retrying a batch makes listings from it."""
        for record_id in self._ids():
            with self.lock(record_id):
                record = self.load(record_id)
                renamed = (
                    None if record is None else rename_template_refs(record.template, old, new)
                )
                if record is not None and renamed is not None:
                    self.save(record.model_copy(update={"template": renamed}))


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
        self._file(batch).unlink(missing_ok=True)
        directory = self._workspace.batch_dir(batch)
        if directory.is_dir():
            remove_tree(directory)

    def review(self, batch_id: str, row_id: str, *, reviewed: bool) -> Batch:
        with self.lock(batch_id):
            batch = self.load(batch_id)
            rows = batch.rows if batch is not None else []
            index = next((i for i, row in enumerate(rows) if row.id == row_id), None)
            if batch is None or index is None:
                raise KeyError(row_id)
            if not reviewable(rows[index]):
                raise NotReviewableError(rows[index].name)
            rows[index] = rows[index].model_copy(update={"reviewed": reviewed})
            self.save(batch)
            return batch

    def rename_listing(self, old: str, new: str) -> None:
        with self.following_rename(old, new):
            pass

    @contextmanager
    def following_rename(self, old: str, new: str) -> Iterator[None]:
        # Lock order: every batch's lock, then the listing write locks, as creating a row
        # takes them; the rows follow only if the body (the move) returns.
        ids = sorted(self._workspace.batch_ids())
        with self._every_lock(ids):
            yield
            for batch_id in ids:
                self._change_rows_locked(
                    batch_id,
                    lambda row: row.name == old and not row.deleted,
                    lambda _: {"name": new},
                )

    @contextmanager
    def _every_lock(self, ids: list[str]) -> Iterator[None]:
        with ExitStack() as held:
            for batch_id in ids:
                held.enter_context(self.lock(batch_id))
            yield

    def mark_deployed(self, listing: str) -> None:
        self._each_row(
            lambda row: row.name == listing and reviewable(row) and not row.reviewed,
            lambda _: {"reviewed": True},
        )

    def mark_deleted(self, listing: str) -> None:
        self._each_row(
            lambda row: row.name == listing and has_listing(row),
            lambda row: {"deleted": True} | ({"ai": "cancelled"} if row.ai == "queued" else {}),
        )

    def restore_listing(self, listing: str, design: str | None) -> None:
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
                self._change_rows_locked(batch_id, which, change)

    def _change_rows_locked(
        self,
        batch_id: str,
        which: Callable[[BatchRow], bool],
        change: Callable[[BatchRow], dict[str, object]],
    ) -> None:
        batch = self.load(batch_id)
        if batch is None or not any(which(row) for row in batch.rows):
            return
        batch.rows[:] = [
            row.model_copy(update=change(row)) if which(row) else row for row in batch.rows
        ]
        self.save(batch)


@dataclass(frozen=True)
class BatchRecords:
    staging: StagingStore
    batches: BatchStore

    def rename_listing_template(self, old: str, new: str) -> None:
        self.staging.rename_listing_template(old, new)
        self.batches.rename_listing_template(old, new)

    def rename_mockup_template(self, old: str, new: str) -> None:
        self.staging.rename_mockup_template(old, new)
        self.batches.rename_mockup_template(old, new)
