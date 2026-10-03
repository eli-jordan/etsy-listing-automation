"""Staging an upload against a listing template, and the session's edits
until it is confirmed or cancelled (batch-creation spec, *Accepted input*,
*Frozen staging*; ADR-0051; module-structure plan, PR 7).

Uploaded bytes and their filenames arrive as ``batches.Upload`` streams --
how they were decoded off a request is the server's. Everything the upload
must satisfy -- PNG or one ZIP, at most 25 designs, the per-file and total
size limits, archive containment and safety -- stays ``batches``' own
(``stage_pngs`` and ``archive``), refused as ``StagingRefused`` with nothing
left on disk. What this module adds is the coordination around it: the
listing template must exist, its content is frozen under its write lock so
a batch never captures a half-written template (ADR-0047), and a session
named in an edit must be there.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from etsy_listings.core.application.refusals import (
    ListingTemplateMissing,
    StagedRowMissing,
    StagingMissing,
)
from etsy_listings.core.application.workspace_locks import WorkspaceLocks
from etsy_listings.core.batches import (
    StagingSession,
    StagingStore,
    Upload,
    stage_pngs,
    upload_path,
)
from etsy_listings.core.workspace.workspace import Workspace


def stage_upload(
    workspace: Workspace,
    staging: StagingStore,
    listing_template: str,
    uploads: Iterable[Upload],
    *,
    locks: WorkspaceLocks,
    now: datetime | None = None,
) -> StagingSession:
    """Stage one ZIP or loose PNGs against ``listing_template``.

    Refusals, nothing on disk: :class:`ListingTemplateMissing`, before any
    upload is read; ``batches.StagingRefused`` for an upload the limits or
    archive checks refuse; ``ConfigLoadError`` for a template whose file will
    not load. The template is captured under its write lock, which is never
    held while the upload streams in (``FrozenListingTemplate.capture``).
    """
    if not workspace.listing_template_file(listing_template).is_file():
        raise ListingTemplateMissing(listing_template)
    return stage_pngs(
        workspace, staging, listing_template, uploads, now=now, template_lock=locks.listing_template
    )


def read_staging(workspace: Workspace, staging: StagingStore, session_id: str) -> StagingSession:
    """The session a reload reattaches to. ``InvalidNameError`` for an id
    that is not a path segment; :class:`StagingMissing` for one nobody
    holds."""
    workspace.staging_dir(session_id)
    session = staging.load(session_id)
    if session is None:
        raise StagingMissing(session_id)
    return session


def edit_staging(
    workspace: Workspace,
    staging: StagingStore,
    session_id: str,
    *,
    label: str | None,
    names: Mapping[str, str],
    remove: Sequence[str],
    now: datetime | None = None,
) -> StagingSession:
    """Relabel, type names, remove rows -- in that order, under the
    session's lock. A blank label keeps the one it had. Every edit moves the
    session's expiry to seven days from ``now``. A row nobody staged refuses
    the whole edit with :class:`StagedRowMissing`, saving none of it."""
    now = now or datetime.now(UTC)
    with staging.lock(session_id):
        session = read_staging(workspace, staging, session_id)
        try:
            if label is not None:
                session = session.relabelled(label.strip() or session.label, now=now)
            for row, name in names.items():
                session = session.renamed(row, name, now=now)
            for row in remove:
                session = session.removed(row, now=now)
        except KeyError as exc:
            raise StagedRowMissing(exc.args[0]) from exc
        staging.save(session)
    return session


def cancel_staging(workspace: Workspace, staging: StagingStore, session_id: str) -> None:
    """Cancel staging: the uploads go at once. The seller's own files were
    never touched."""
    with staging.lock(session_id):
        read_staging(workspace, staging, session_id)
        staging.remove(session_id)


def staged_upload(workspace: Workspace, staging: StagingStore, session_id: str, row: str) -> Path:
    """Where a staged row's bytes are -- its thumbnail's source."""
    session = read_staging(workspace, staging, session_id)
    try:
        return upload_path(workspace, session, row)
    except KeyError as exc:
        raise StagedRowMissing(row) from exc
