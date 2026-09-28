"""Confirming a staging session: the batch record, then one listing per row
(spec *Confirming a batch*; A38, A39, A46).

The record is written first, with every row's allocated name and
``creation: pending``, and before any file. Each row then:

1. writes ``designs/<design>.png``, or reuses the file already there when its
   bytes are the row's;
2. copies the frozen listing template's owned files into ``listings/<name>/``;
3. writes ``listing.yaml`` atomically;
4. records ``creation: created``.

Every step can be repeated, so Retry, a second confirm, or a confirm after a
crash re-enters at whatever the disk and the record say is done. A directory
already at the row's name is the row's own when its ``listing.yaml`` names the
row's design, or when it has none and the record says the row claimed it;
anything else there belongs to somebody else, and the row takes a fresh
suffix instead (A39). A failure is recorded on its row with the sentence and
the next row carries on.

The staging session goes once every row is materialised -- created, or failed
with its upload copied beside the batch for Retry (A46).
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from etsy_listings.batches.naming import allocate
from etsy_listings.batches.records import Batch, BatchRow, BatchStore, StagingStore
from etsy_listings.batches.staging import review, workspace_names
from etsy_listings.config.errors import ConfigLoadError
from etsy_listings.config.listing import Listing
from etsy_listings.config.listing_template import ListingTemplate
from etsy_listings.errors import UserFacingError
from etsy_listings.listing_templates import owned_refs
from etsy_listings.listing_templates.check import check_listing_template_files
from etsy_listings.workspace import layout
from etsy_listings.workspace.atomic import write_bytes_atomic
from etsy_listings.workspace.facts import WorkspaceFacts
from etsy_listings.workspace.workspace import Workspace

NameLock = Callable[[str], AbstractContextManager[object]]
"""A listing name's write lock -- the UI's ``WorkspaceLocks.listing`` -- held
while a row's name is checked and its files are written (A38)."""


def _no_lock(_: str) -> AbstractContextManager[object]:
    return nullcontext()


class ConfirmRefused(UserFacingError, ValueError):
    """The session cannot become a batch yet, and nothing was written."""


def _template(workspace: Workspace, batch: Batch) -> ListingTemplate:
    return ListingTemplate.model_validate(
        batch.template, context={"currency": workspace.defaults.etsy.currency}
    )


def _revalidate(workspace: Workspace, template: ListingTemplate, frozen: Path, name: str) -> None:
    """The frozen document's shared refs -- garment profile, pricing plan,
    common copy, mockup templates -- may have changed since staging began
    (spec, *Design validation*)."""
    issues = check_listing_template_files(
        workspace,
        template,
        resolve=lambda ref: workspace.resolve_frozen_template_ref(ref, frozen_dir=frozen),
        facts=WorkspaceFacts.gather(workspace),
    )
    blocking = [issue.message for issue in issues if issue.severity == "block"]
    if blocking:
        raise ConfirmRefused(f"{name} as staged can no longer make listings: {' '.join(blocking)}")


def confirm(
    workspace: Workspace,
    staging: StagingStore,
    batches: BatchStore,
    session_id: str,
    *,
    lock: NameLock = _no_lock,
    now: datetime | None = None,
) -> Batch:
    """Create the batch for ``session_id`` and its listings, or finish the
    one a previous confirm began. Raises :class:`KeyError` for a session that
    does not exist and :class:`ConfirmRefused` for one that cannot be
    confirmed yet."""
    with staging.lock(session_id), batches.lock(session_id):
        batch = batches.load(session_id)
        if batch is None:
            batch = _start(workspace, staging, batches, session_id, lock, now or datetime.now(UTC))
    return create_rows(workspace, staging, batches, session_id, lock=lock)


def _start(
    workspace: Workspace,
    staging: StagingStore,
    batches: BatchStore,
    session_id: str,
    lock: NameLock,
    now: datetime,
) -> Batch:
    session = staging.load(session_id)
    if session is None:
        raise KeyError(session_id)
    reviewed = review(workspace, session)
    if reviewed.name_problems:
        count = reviewed.name_problems
        raise ConfirmRefused(
            f"Fix {count} {'name' if count == 1 else 'names'} to create the listings."
        )
    if not reviewed.creatable:
        raise ConfirmRefused("There is no design here that can become a listing.")
    template = ListingTemplate.model_validate(
        session.template, context={"currency": workspace.defaults.etsy.currency}
    )
    frozen = workspace.staging_template_dir(session_id)
    _revalidate(workspace, template, frozen, session.listing_template)
    # Kept for Retry after the staging session has gone (A37).
    shutil.copytree(frozen, workspace.batch_template_dir(session_id), dirs_exist_ok=True)
    by_id = {row.id: row for row in session.rows}
    others = {row.name.casefold() for row in reviewed.creatable}
    allocated: set[str] = set()
    rows: list[BatchRow] = []
    for row in reviewed.creatable:
        # A38: the preview may be stale; the name is checked again under the
        # listing's lock and recorded before any file is written.
        with lock(row.name):
            taken = set(workspace_names(workspace)) | allocated | (others - {row.name.casefold()})
            name = allocate(row.name, taken)
        allocated.add(name.casefold())
        staged = by_id[row.id]
        rows.append(
            BatchRow(
                id=row.id,
                sha256=staged.sha256,
                sources=staged.sources,
                base=row.name,
                name=name,
                design=name,
            )
        )
    batch = Batch(
        id=session_id,
        listing_template=session.listing_template,
        template=session.template,
        template_saved_at=session.template_saved_at,
        label=session.label,
        created_at=now,
        rows=rows,
    )
    batches.save(batch)
    return batch


def retry_row(
    workspace: Workspace,
    staging: StagingStore,
    batches: BatchStore,
    batch_id: str,
    row_id: str,
    *,
    lock: NameLock = _no_lock,
) -> Batch:
    """Retry creating one row (UI doc §7). A created row is left alone.
    Raises :class:`KeyError` for a batch or row that does not exist."""
    batch = batches.load(batch_id)
    if batch is None or all(row.id != row_id for row in batch.rows):
        raise KeyError(row_id)
    return create_rows(workspace, staging, batches, batch_id, lock=lock, only={row_id})


def create_rows(
    workspace: Workspace,
    staging: StagingStore,
    batches: BatchStore,
    batch_id: str,
    *,
    lock: NameLock = _no_lock,
    only: set[str] | None = None,
) -> Batch:
    """Create every row still to create (A39), recording each outcome as it
    lands, then drop the staging session if nothing needs it any more."""
    with batches.lock(batch_id):
        batch = batches.load(batch_id)
        if batch is None:
            raise KeyError(batch_id)
        template = _template(workspace, batch)
        for index, row in enumerate(batch.rows):
            if row.creation == "created" or (only is not None and row.id not in only):
                continue
            try:
                row = _create(workspace, batches, batch, index, template, lock)
            except (OSError, ConfigLoadError, ValidationError, UserFacingError) as exc:
                row = batch.rows[index].model_copy(
                    update={"creation": "failed", "error": _failure(row, exc)}
                )
                _keep_input(workspace, batch, row)
            batch.rows[index] = row
            batches.save(batch)
    if all(_materialised(workspace, batch, row) for row in batch.rows):
        with staging.lock(batch_id):
            staging.remove(batch_id)
    return batch


def _failure(row: BatchRow, exc: Exception) -> str:
    if isinstance(exc, OSError):
        detail = exc.strerror or str(exc)
        where = exc.filename or f"{layout.LISTINGS_DIR}/{row.name}/"
        return f"Couldn't write {where}: {detail}. Fix that, then Retry."
    return f"Couldn't create {row.name}: {exc}"


def row_upload(workspace: Workspace, batch: Batch, row_id: str) -> Path:
    """The upload a row was made from, wherever it is kept now: beside the
    batch once its creation failed (A46), else still in staging. What a row
    that was never created shows as its thumbnail on the summary, since it
    has no listing design to show. :class:`KeyError` for a row the batch
    does not have; the path may not exist once the staging session has
    gone."""
    row = next((r for r in batch.rows if r.id == row_id), None)
    if row is None:
        raise KeyError(row_id)
    return _input(workspace, batch, row)


def _input(workspace: Workspace, batch: Batch, row: BatchRow) -> Path:
    kept = workspace.batch_upload_file(batch.id, row.sha256)
    return kept if kept.is_file() else workspace.staging_upload_file(batch.id, row.sha256)


def _keep_input(workspace: Workspace, batch: Batch, row: BatchRow) -> None:
    """A failed row's upload moves beside the batch, so Retry still has it
    once the staging session is gone (A46). If even that fails, the staging
    session stays."""
    source = workspace.staging_upload_file(batch.id, row.sha256)
    target = workspace.batch_upload_file(batch.id, row.sha256)
    if source.is_file() and not target.is_file():
        with suppress(OSError):
            write_bytes_atomic(target, source.read_bytes())


def _materialised(workspace: Workspace, batch: Batch, row: BatchRow) -> bool:
    return row.creation == "created" or workspace.batch_upload_file(batch.id, row.sha256).is_file()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_ours(workspace: Workspace, row: BatchRow) -> bool:
    """May this row write at its recorded name? (A39)"""
    design = workspace.design_file(row.design)
    if design.is_file() and _sha256(design) != row.sha256:
        return False
    directory = workspace.listing_dir(row.name)
    if not directory.exists():
        return True
    listing = directory / layout.LISTING_FILE
    if not listing.is_file():
        return row.claimed and not workspace.lock_file(row.name).exists()
    raw = yaml.safe_load(listing.read_text(encoding="utf-8")) or {}
    ref = raw.get("design") if isinstance(raw, dict) else None
    if isinstance(ref, dict):
        ref = ref.get("default") if len(ref) == 1 else None
    return bool(ref == workspace.design_ref(row.design))


def _create(
    workspace: Workspace,
    batches: BatchStore,
    batch: Batch,
    index: int,
    template: ListingTemplate,
    lock: NameLock,
) -> BatchRow:
    row = batch.rows[index]
    while True:
        with lock(row.name):
            if _is_ours(workspace, row):
                if not row.claimed:
                    row = row.model_copy(update={"claimed": True})
                    batch.rows[index] = row
                    batches.save(batch)
                _write(workspace, batch, row, template)
                # Created is queued (spec, *Confirming a batch*), in the same
                # save, so a crash cannot leave a listing the queue never sees.
                return row.model_copy(update={"creation": "created", "error": None, "ai": "queued"})
        others = {r.name.casefold() for i, r in enumerate(batch.rows) if i != index}
        name = allocate(row.base, set(workspace_names(workspace)) | others)
        row = row.model_copy(update={"name": name, "design": name, "claimed": False})
        batch.rows[index] = row
        batches.save(batch)


def _put(workspace: Workspace, target: Path, data: bytes) -> None:
    """One atomic write, whose failure names the file the seller would look
    for -- ``designs/x.png`` -- rather than the temporary beside it."""
    try:
        write_bytes_atomic(target, data)
    except OSError as exc:
        where = target.relative_to(workspace.root).as_posix()
        raise OSError(exc.errno, exc.strerror or str(exc), where) from exc


def _write(workspace: Workspace, batch: Batch, row: BatchRow, template: ListingTemplate) -> None:
    listing_dir = workspace.listing_dir(row.name)
    listing_dir.mkdir(parents=True, exist_ok=True)
    design = workspace.design_file(row.design)
    if not design.is_file():
        _put(workspace, design, _input(workspace, batch, row).read_bytes())
    frozen = workspace.batch_template_dir(batch.id)
    for ref in owned_refs(template):
        source = workspace.resolve_frozen_template_ref(ref, frozen_dir=frozen)
        _put(workspace, workspace.resolve_ref(ref, listing_dir=listing_dir), source.read_bytes())
    document = _listing_document(workspace, template, row.design)
    Listing.model_validate(document, context={"currency": workspace.defaults.etsy.currency})
    _put(
        workspace,
        workspace.listing_file(row.name),
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True).encode("utf-8"),
    )


def _listing_document(
    workspace: Workspace, template: ListingTemplate, design: str
) -> dict[str, Any]:
    """The frozen template as an ordinary listing (spec, *Confirming a
    batch*): the single-file design ref, an empty brief, and blank title,
    tags and lead for the seller to accept suggestions into. ``./`` refs are
    kept as they are; the files they name were just copied beside it."""
    body = template.model_dump(mode="json", exclude_defaults=True)
    etsy = body.pop("etsy", {})
    description = etsy.pop("description", {})
    return {
        "garment_profile": body.pop("garment_profile"),
        "design": {"default": workspace.design_ref(design)},
        "colors": body.pop("colors"),
        "brief": "",
        **{key: value for key, value in body.items() if key != "media"},
        "etsy": {"title": "", "description": {"lead": "", **description}, "tags": [], **etsy},
        "media": body["media"],
    }
