"""Staging one ZIP or loose PNGs, and the review of what was staged (spec
*Accepted input*, *Frozen staging*, *Staging validation and naming*,
*Content deduplication*; A38, A45).

:func:`stage_pngs` is the one write: it streams each PNG -- loose, or read
out of the ZIP by `archive` -- to ``uploads/<sha256>.png``, merges identical
bytes into one row, refuses more than 25 designs, freezes the listing
template and checks every design against its garment, then writes
``session.json`` last. Any refusal removes the session's directory, so a
refused upload leaves nothing on disk (A45).

:func:`review` writes nothing. Names depend on the workspace -- a listing
created a minute ago takes its name from a generated row -- so they are
worked out on every read from the stored base names rather than stored,
and so is which ``designs/`` file a row's bytes already are.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Iterable, Iterator
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Literal

from etsy_listings.batches import archive as archive_file
from etsy_listings.batches.archive import PNG_MAGIC, ArchiveRefused
from etsy_listings.batches.naming import allocate
from etsy_listings.batches.records import StagingRow, StagingSession, StagingStore
from etsy_listings.config.errors import ConfigLoadError
from etsy_listings.config.listing_validation import check_design_resolution
from etsy_listings.config.slug import slugify
from etsy_listings.errors import UserFacingError
from etsy_listings.listing_templates import FrozenListingTemplate, TemplateLock
from etsy_listings.workspace.atomic import read_bytes_retrying
from etsy_listings.workspace.workspace import Workspace, remove_tree

# A45: safety limits, not settings. Module attributes so a test can lower them.
MAX_DESIGNS = 25
MAX_PNG_BYTES = 64 * 1024 * 1024
MAX_UPLOAD_BYTES = 512 * 1024 * 1024

_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06")
_CHUNK = 1024 * 1024

_UNDO = "Nothing was uploaded or changed."


class StagingRefused(UserFacingError, ValueError):
    """The upload as a whole cannot be staged. ``message`` says why, the page
    heading it *... was not staged*; ``remedy`` says how to fix it and always
    ends by saying nothing was kept (UI doc §4)."""

    def __init__(self, message: str, remedy: str) -> None:
        self.message = message
        self.remedy = remedy
        super().__init__(f"{message} {remedy}")


@dataclass(frozen=True)
class Upload:
    filename: str
    stream: BinaryIO


def _stem(filename: str) -> str:
    return PurePosixPath(filename.replace("\\", "/")).stem


class _Received:
    """The unique designs of one upload, stored under their content hash as
    they stream in (A45). Identical bytes become one row that names every
    source (spec, *Content deduplication*)."""

    def __init__(self, workspace: Workspace, session: str, total_limit: int | None) -> None:
        self._workspace = workspace
        self._session = session
        self._total_limit = total_limit
        self._total = 0
        self.rows: dict[str, StagingRow] = {}
        self._incoming = workspace.staging_upload_file(session, "incoming")
        self._incoming.parent.mkdir(parents=True, exist_ok=True)

    def add(self, name: str, chunks: Iterable[bytes]) -> None:
        digest = hashlib.sha256()
        size = 0
        with self._incoming.open("wb") as out:
            for chunk in chunks:
                size += len(chunk)
                self._total += len(chunk)
                if size > MAX_PNG_BYTES:
                    raise StagingRefused(
                        f"{name} is larger than {MAX_PNG_BYTES // 2**20} MiB.",
                        f"Export it smaller, or leave it out. {_UNDO}",
                    )
                if self._total_limit is not None and self._total > self._total_limit:
                    raise StagingRefused(
                        f"These files are larger than {self._total_limit // 2**20} MiB together.",
                        f"Stage fewer at a time. {_UNDO}",
                    )
                digest.update(chunk)
                out.write(chunk)
        sha = digest.hexdigest()
        if sha in self.rows:
            self.rows[sha].sources.append(name)
            self._incoming.unlink()
            return
        self._incoming.replace(self._workspace.staging_upload_file(self._session, sha))
        self.rows[sha] = StagingRow(
            id=sha[:16], sha256=sha, sources=[name], base=slugify(_stem(name))
        )


def _chunks(head: bytes, stream: BinaryIO) -> Iterator[bytes]:
    chunk = head
    while chunk:
        yield chunk
        chunk = stream.read(_CHUNK)


def _is_zip(upload: Upload, head: bytes) -> bool:
    return head.startswith(_ZIP_MAGICS) or upload.filename.lower().endswith(".zip")


@dataclass(frozen=True)
class _Receipt:
    rows: list[StagingRow]
    ignored: list[str]
    """The names of the ZIP's files that are not PNGs."""
    archive: str | None
    """The ZIP's own name, without folders or ``.zip``; ``None`` for loose
    PNGs. It leads the default label (spec, *Confirming a batch*)."""


def _archive_name(filename: str) -> str:
    """``C:\\exports\\Coding x Music.zip`` -> ``Coding x Music``: a browser
    sends the bare name, but a name with folders is still only its last part."""
    name = re.split(r"[\\/]", filename)[-1]
    return name[: -len(".zip")] if name.lower().endswith(".zip") else name


def _receive(workspace: Workspace, session: str, uploads: Iterable[Upload]) -> _Receipt:
    """Every design in the upload. One ZIP, or loose PNGs, never both (spec,
    *Accepted input*)."""
    heads = [(upload, upload.stream.read(len(PNG_MAGIC))) for upload in uploads]
    zips = [upload for upload, head in heads if _is_zip(upload, head)]
    if len(zips) > 1:
        raise StagingRefused(
            f"These are {len(zips)} ZIPs, and a batch takes one.",
            f"Start a batch for each ZIP. {_UNDO}",
        )
    if zips and len(heads) > 1:
        raise StagingRefused(
            "These are a ZIP and loose files together, and a batch takes one or the other.",
            f"Put the PNGs in the ZIP, or drop them without it. {_UNDO}",
        )
    if zips:
        ((upload, head),) = heads
        received = _Received(workspace, session, total_limit=None)
        ignored = _receive_zip(workspace, session, upload, head, received)
        _limit(received, "It holds", "Split the export into {} ZIPs and start a batch for each.")
        return _Receipt(list(received.rows.values()), ignored, _archive_name(upload.filename))
    received = _Received(workspace, session, total_limit=MAX_UPLOAD_BYTES)
    for upload, head in heads:
        if head != PNG_MAGIC:
            raise StagingRefused(
                f"{upload.filename} is not a PNG.", f"Drop only PNG design files. {_UNDO}"
            )
        received.add(upload.filename, _chunks(head, upload.stream))
    if not received.rows:
        raise StagingRefused("No files were dropped.", "Choose at least one PNG.")
    _limit(received, "They hold", "Split them into {} batches.")
    return _Receipt(list(received.rows.values()), [], None)


_SPLITS = {2: "two", 3: "three", 4: "four"}


def _limit(received: _Received, subject: str, remedy: str) -> None:
    """More than 25 unique designs is refused, never truncated or split
    (spec, *Accepted input*). The remedy says into how many."""
    count = len(received.rows)
    if count > MAX_DESIGNS:
        parts = -(-count // MAX_DESIGNS)
        raise StagingRefused(
            f"{subject} {count} different PNG designs, and a batch takes at most {MAX_DESIGNS}.",
            f"{remedy.format(_SPLITS.get(parts, str(parts)))} {_UNDO}",
        )


def _receive_zip(
    workspace: Workspace, session: str, upload: Upload, head: bytes, received: _Received
) -> list[str]:
    """Stream the ZIP to disk, then read each PNG out of it entry by entry
    (A45); the ZIP itself goes before the session is saved."""
    path = workspace.staging_archive_file(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        archive_file.receive(_chunks(head, upload.stream), path)
        with archive_file.open_archive(path) as archive:
            for name in archive.pngs:
                received.add(name, archive.read(name))
            return archive.ignored
    except ArchiveRefused as exc:
        raise StagingRefused(exc.message, f"{exc.remedy} {_UNDO}") from exc
    finally:
        path.unlink(missing_ok=True)


def _default_label(listing_template: str, now: datetime, archive: str | None = None) -> str:
    """The listing template and the date and time, in the server's local
    time -- the seller's, for a desktop tool -- led by the ZIP's name when
    the designs came in one (spec, *Confirming a batch*)."""
    local = now.astimezone()
    label = f"{listing_template} · {local.day} {local:%b %H:%M}"
    return f"{archive} · {label}" if archive else label


def stage_pngs(
    workspace: Workspace,
    store: StagingStore,
    listing_template: str,
    uploads: Iterable[Upload],
    *,
    now: datetime | None = None,
    template_lock: TemplateLock = lambda _: nullcontext(),
) -> StagingSession:
    """Stage ``uploads`` against ``listing_template``, or raise
    :class:`StagingRefused` with nothing left on disk.

    Each row is checked with the existing design rules against the frozen
    template's garment profile (spec, *Design validation*); a design that
    fails is a row that will not be created, not a refusal of the upload."""
    now = now or datetime.now(UTC)
    session = uuid.uuid4().hex
    directory = workspace.staging_dir(session)
    try:
        frozen = FrozenListingTemplate.capture(
            workspace, listing_template, workspace.staging_template_dir(session), lock=template_lock
        )
        template = frozen.template
        try:
            profile = workspace.load_garment_profile(template.garment_profile)
        except ConfigLoadError as exc:
            raise StagingRefused(f"{listing_template} cannot be used: {exc}", _UNDO) from exc
        receipt = _receive(workspace, session, uploads)
        rows, ignored = receipt.rows, receipt.ignored
        for row in rows:
            path = workspace.staging_upload_file(session, row.sha256)
            issues = check_design_resolution(path, profile)
            if issues:
                # The rule's own sentence, naming the file the seller dropped
                # rather than the hash it is stored under.
                message = issues[0].message.replace(str(path), path.name)
                row.error = message.replace(path.name, row.sources[0])
        record = StagingSession(
            id=session,
            listing_template=listing_template,
            template=template.model_dump(mode="json"),
            template_saved_at=frozen.saved_at,
            label=_default_label(listing_template, now, receipt.archive),
            created_at=now,
            updated_at=now,
            rows=rows,
            ignored=ignored,
        )
        store.save(record)
    except BaseException:
        if directory.exists():
            remove_tree(directory)
        raise
    return record


RowState = Literal["ready", "name", "invalid"]


@dataclass(frozen=True)
class RowReview:
    id: str
    sources: list[str]
    name: str
    typed: bool
    state: RowState
    """``ready`` will be created; ``name`` blocks Create until the seller
    fixes the name; ``invalid`` will not be created and does not block."""
    message: str | None = None
    note: str | None = None
    suggestion: str | None = None
    reuse: str | None = None
    """The stem of the ``designs/`` file with this row's exact bytes, which
    the listing will name instead of writing its own (spec, *Content
    deduplication*)."""


@dataclass(frozen=True)
class StagingReview:
    session: StagingSession
    rows: list[RowReview]

    @property
    def creatable(self) -> list[RowReview]:
        return [row for row in self.rows if row.state == "ready"]

    @property
    def name_problems(self) -> int:
        return sum(1 for row in self.rows if row.state == "name")


def workspace_names(workspace: Workspace) -> dict[str, str]:
    """Every name a batch row must not take, casefolded, and what holds it:
    listing directories (with a ``listing.yaml`` or not -- create refuses
    either) and design stems (A38)."""
    taken = {path.stem.casefold(): "design" for path in workspace.design_files()}
    return taken | {name.casefold(): "listing" for name in workspace.listing_directory_names()}


def designs_by_content(workspace: Workspace, sizes: dict[str, int]) -> dict[str, str]:
    """The ``designs/`` stem holding each of these contents, by SHA-256, for
    the ones some design holds (spec, *Content deduplication*). ``sizes``
    maps each wanted hash to its byte count: identical bytes are the same
    length, so only a design of a wanted length is ever read, and a review
    does not hash the whole of ``designs/`` on every read. The first design
    by name wins when two hold the same bytes."""
    lengths = set(sizes.values())
    found: dict[str, str] = {}
    for path in sorted(workspace.design_files()):
        if path.stat().st_size not in lengths:
            continue
        # A confirm may be writing designs/ atomically at the same moment,
        # which Windows answers with a PermissionError on open.
        sha = hashlib.sha256(read_bytes_retrying(path)).hexdigest()
        if sha in sizes:
            found.setdefault(sha, path.stem)
    return found


def taken_for(workspace_taken: dict[str, str], reuse: str | None) -> set[str]:
    """What a row may not be named. A row reusing ``designs/<r>.png`` may
    take ``r`` itself when nothing but that design holds it, since its one
    name then drives both paths as A38 intends -- the listing ``r`` over the
    design ``r`` -- rather than a needless ``r-2`` over ``designs/r.png``."""
    taken = set(workspace_taken)
    if reuse is not None and workspace_taken.get(reuse.casefold()) == "design":
        taken.discard(reuse.casefold())
    return taken


def _typed_problem(name: str, holder: str | None) -> str | None:
    if not name:
        return "Type a name for this listing."
    if slugify(name) != name:
        return f"{name} can only use lowercase letters, digits and hyphens."
    if holder == "listing":
        return f"{name} is already a listing."
    if holder == "design":
        return f"{name} is already a design in designs/."
    if holder == "row":
        return f"{name} is already used by another design in this batch."
    return None


def review(workspace: Workspace, session: StagingSession) -> StagingReview:
    """Every row's name, state and note (A38; UI doc §5).

    Typed names are claimed first and never changed: one that is taken is
    flagged, with the next free suffix as a suggestion. Generated names then
    take the smallest free suffix around the workspace, the typed names and
    each other, in upload order. Rows that will not be created claim
    nothing."""
    workspace_taken = workspace_names(workspace)
    valid = [row for row in session.rows if row.error is None]
    typed: dict[str, str] = {}
    for row in valid:
        if row.typed and row.base:
            typed.setdefault(row.base.casefold(), row.id)
    reused = designs_by_content(
        workspace,
        {
            row.sha256: workspace.staging_upload_file(session.id, row.sha256).stat().st_size
            for row in valid
        },
    )
    allocated: set[str] = set()
    reviews: list[RowReview] = []
    for row in session.rows:
        note = (
            f"{len(row.sources)} identical files, staged once: {', '.join(row.sources)}"
            if len(row.sources) > 1
            else None
        )
        name = row.base
        state: RowState = "ready"
        message: str | None = None
        suggestion: str | None = None
        reuse = reused.get(row.sha256) if row.error is None else None
        if reuse is not None:
            same = f"Same image as designs/{reuse}.png. The listing reuses that file"
            note = f"{note}; {same}" if note else same
        taken = taken_for(workspace_taken, reuse)
        claimed = taken | set(typed)
        if row.error is not None:
            state, message, note = "invalid", row.error, None
        elif row.typed:
            folded = row.base.casefold()
            holder = (workspace_taken.get(folded) if folded in taken else None) or (
                "row" if typed.get(folded) != row.id else None
            )
            message = _typed_problem(row.base, holder)
            if message:
                state = "name"
                if slugify(row.base):
                    suggestion = allocate(slugify(row.base), claimed | allocated)
            allocated.add(folded)
        elif not row.base:
            state = "name"
            message = "The file name has no letters or digits. Type a name for this listing."
        else:
            name = allocate(row.base, claimed | allocated)
            allocated.add(name.casefold())
            if name != row.base:
                suffixed = f"{row.base} is taken, so {name.removeprefix(row.base)} was added"
                note = f"{note}; {suffixed}" if note else suffixed
        reviews.append(
            RowReview(
                id=row.id,
                sources=row.sources,
                name=name,
                typed=row.typed,
                state=state,
                message=message,
                note=note,
                suggestion=suggestion,
                reuse=reuse,
            )
        )
    return StagingReview(session=session, rows=reviews)


def upload_path(workspace: Workspace, session: StagingSession, row: str) -> Path:
    """Where row ``row``'s bytes are, for its thumbnail."""
    for candidate in session.rows:
        if candidate.id == row:
            return workspace.staging_upload_file(session.id, candidate.sha256)
    raise KeyError(row)
