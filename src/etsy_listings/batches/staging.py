"""Staging loose PNGs, and the review of what was staged (spec *Accepted
input*, *Frozen staging*, *Staging validation and naming*; A38, A45).

:func:`stage_pngs` is the one write: it streams each upload to
``uploads/<sha256>.png``, merges identical bytes into one row, refuses more
than 25 designs, freezes the listing template and checks every design against
its garment, then writes ``session.json`` last. Any refusal removes the
session's directory, so a refused upload leaves nothing on disk (A45).

:func:`review` writes nothing. Names depend on the workspace -- a listing
created a minute ago takes its name from a generated row -- so they are
worked out on every read from the stored base names rather than stored.
"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Literal

from etsy_listings.batches.naming import allocate
from etsy_listings.batches.records import StagingRow, StagingSession, StagingStore
from etsy_listings.config.errors import ConfigLoadError
from etsy_listings.config.listing_validation import check_design_resolution
from etsy_listings.config.slug import slugify
from etsy_listings.errors import UserFacingError
from etsy_listings.listing_templates import owned_refs
from etsy_listings.workspace.workspace import Workspace, remove_tree

# A45: safety limits, not settings. Module attributes so a test can lower them.
MAX_DESIGNS = 25
MAX_PNG_BYTES = 64 * 1024 * 1024
MAX_UPLOAD_BYTES = 512 * 1024 * 1024

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
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


def _receive(workspace: Workspace, session: str, uploads: Iterable[Upload]) -> list[StagingRow]:
    """Stream every upload to disk under its content hash, with a running
    byte count rather than reading it whole (A45). Identical bytes become
    one row that names every source (spec, *Content deduplication*)."""
    rows: dict[str, StagingRow] = {}
    total = 0
    incoming = workspace.staging_upload_file(session, "incoming")
    incoming.parent.mkdir(parents=True, exist_ok=True)
    for upload in uploads:
        name = upload.filename
        digest = hashlib.sha256()
        size = 0
        with incoming.open("wb") as out:
            head = upload.stream.read(len(_PNG_MAGIC))
            if head.startswith(_ZIP_MAGICS) or name.lower().endswith(".zip"):
                raise StagingRefused(
                    f"{name} is a ZIP, and ZIP files are coming soon.",
                    f"Drop the PNGs themselves for now. {_UNDO}",
                )
            if head != _PNG_MAGIC:
                raise StagingRefused(
                    f"{name} is not a PNG.", f"Drop only PNG design files. {_UNDO}"
                )
            chunk = head
            while chunk:
                size += len(chunk)
                total += len(chunk)
                if size > MAX_PNG_BYTES:
                    raise StagingRefused(
                        f"{name} is larger than {MAX_PNG_BYTES // 2**20} MiB.",
                        f"Export it smaller, or leave it out. {_UNDO}",
                    )
                if total > MAX_UPLOAD_BYTES:
                    raise StagingRefused(
                        f"These files are larger than {MAX_UPLOAD_BYTES // 2**20} MiB together.",
                        f"Stage fewer at a time. {_UNDO}",
                    )
                digest.update(chunk)
                out.write(chunk)
                chunk = upload.stream.read(_CHUNK)
        sha = digest.hexdigest()
        if sha in rows:
            rows[sha].sources.append(name)
            incoming.unlink()
            continue
        incoming.replace(workspace.staging_upload_file(session, sha))
        rows[sha] = StagingRow(id=sha[:16], sha256=sha, sources=[name], base=slugify(_stem(name)))
    if not rows:
        raise StagingRefused("No files were dropped.", "Choose at least one PNG.")
    if len(rows) > MAX_DESIGNS:
        raise StagingRefused(
            f"They hold {len(rows)} different PNG designs, and a batch takes at "
            f"most {MAX_DESIGNS}.",
            f"Split them into smaller batches. {_UNDO}",
        )
    return list(rows.values())


def _freeze(workspace: Workspace, session: str, template: str, refs: list[str]) -> None:
    """Copy the template's owned files beside the session, where the frozen
    document's ``./`` refs now resolve (spec, *Frozen staging*)."""
    frozen = workspace.staging_template_dir(session)
    frozen.mkdir(parents=True, exist_ok=True)
    for ref in refs:
        source = workspace.resolve_template_ref(ref, template=template)
        target = workspace.resolve_frozen_template_ref(ref, frozen_dir=frozen)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def _default_label(listing_template: str, now: datetime) -> str:
    """The listing template and the date and time, in the server's local
    time -- the seller's, for a desktop tool (spec, *Confirming a batch*)."""
    local = now.astimezone()
    return f"{listing_template} · {local.day} {local:%b %H:%M}"


def stage_pngs(
    workspace: Workspace,
    store: StagingStore,
    listing_template: str,
    uploads: Iterable[Upload],
    *,
    now: datetime | None = None,
) -> StagingSession:
    """Stage ``uploads`` against ``listing_template``, or raise
    :class:`StagingRefused` with nothing left on disk.

    Each row is checked with the existing design rules against the frozen
    template's garment profile (spec, *Design validation*); a design that
    fails is a row that will not be created, not a refusal of the upload."""
    now = now or datetime.now(UTC)
    template = workspace.load_listing_template(listing_template)
    try:
        profile = workspace.load_garment_profile(template.garment_profile)
    except ConfigLoadError as exc:
        raise StagingRefused(f"{listing_template} cannot be used: {exc}", _UNDO) from exc
    session = uuid.uuid4().hex
    directory = workspace.staging_dir(session)
    try:
        rows = _receive(workspace, session, uploads)
        _freeze(workspace, session, listing_template, owned_refs(template))
        for row in rows:
            path = workspace.staging_upload_file(session, row.sha256)
            issues = check_design_resolution(path, profile)
            if issues:
                # The rule's own sentence, naming the file the seller dropped
                # rather than the hash it is stored under.
                message = issues[0].message.replace(str(path), path.name)
                row.error = message.replace(path.name, row.sources[0])
        saved_at = workspace.listing_template_file(listing_template).stat().st_mtime
        record = StagingSession(
            id=session,
            listing_template=listing_template,
            template=template.model_dump(mode="json"),
            template_saved_at=datetime.fromtimestamp(saved_at, tz=UTC),
            label=_default_label(listing_template, now),
            created_at=now,
            updated_at=now,
            rows=rows,
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
    claimed = set(workspace_taken) | set(typed)
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
        if row.error is not None:
            state, message, note = "invalid", row.error, None
        elif row.typed:
            folded = row.base.casefold()
            holder = workspace_taken.get(folded) or ("row" if typed.get(folded) != row.id else None)
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
            )
        )
    return StagingReview(session=session, rows=reviews)


def upload_path(workspace: Workspace, session: StagingSession, row: str) -> Path:
    """Where row ``row``'s bytes are, for its thumbnail."""
    for candidate in session.rows:
        if candidate.id == row:
            return workspace.staging_upload_file(session.id, candidate.sha256)
    raise KeyError(row)
