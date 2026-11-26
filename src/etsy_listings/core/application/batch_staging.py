from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from etsy_listings.core.application.refusals import (
    ListingTemplateMissingError,
    StagedRowMissingError,
    StagingMissingError,
)
from etsy_listings.core.batches import (
    StagingSession,
    StagingStore,
    Upload,
    stage_pngs,
    upload_path,
)
from etsy_listings.core.workspace.workspace import Workspace


def stage_upload(
    staging: StagingStore,
    listing_template: str,
    uploads: Iterable[Upload],
    *,
    now: datetime | None = None,
) -> StagingSession:
    """Stage one ZIP or loose PNGs against ``listing_template``.

    Refusals, nothing on disk: :class:`ListingTemplateMissingError`, before any
    upload is read; ``batches.StagingRefusedError`` for an upload the limits or
    archive checks refuse; ``ConfigLoadError`` for a template whose file will
    not load. The template is captured under its write lock, which is never
    held while the upload streams in (``FrozenListingTemplate.capture``).
    """
    if not staging.workspace.listing_template_file(listing_template).is_file():
        raise ListingTemplateMissingError(listing_template)
    return stage_pngs(staging, listing_template, uploads, now=now)


def read_staging(workspace: Workspace, staging: StagingStore, session_id: str) -> StagingSession:
    """The session a reload reattaches to. ``InvalidNameError`` for an id
    that is not a path segment; :class:`StagingMissingError` for one nobody
    holds."""
    workspace.staging_dir(session_id)
    session = staging.load(session_id)
    if session is None:
        raise StagingMissingError(session_id)
    return session


@dataclass(frozen=True)
class StagingEdit:
    """One edit of a staging session: a new label (``None`` keeps it), names
    typed for rows, and rows to remove."""

    label: str | None = None
    names: Mapping[str, str] = field(default_factory=dict)
    remove: Sequence[str] = ()


def edit_staging(
    workspace: Workspace,
    staging: StagingStore,
    session_id: str,
    edit: StagingEdit,
    *,
    now: datetime | None = None,
) -> StagingSession:
    """Relabel, type names, remove rows -- in that order, under the
    session's lock. A blank label keeps the one it had. Every edit moves the
    session's expiry to seven days from ``now``. A row nobody staged refuses
    the whole edit with :class:`StagedRowMissingError`, saving none of it."""
    now = now or datetime.now(UTC)
    with staging.lock(session_id):
        session = read_staging(workspace, staging, session_id)
        try:
            if edit.label is not None:
                session = session.relabelled(edit.label.strip() or session.label, now=now)
            for row, name in edit.names.items():
                session = session.renamed(row, name, now=now)
            for row in edit.remove:
                session = session.removed(row, now=now)
        except KeyError as exc:
            raise StagedRowMissingError(exc.args[0]) from exc
        staging.save(session)
    return session


def cancel_staging(workspace: Workspace, staging: StagingStore, session_id: str) -> None:
    with staging.lock(session_id):
        read_staging(workspace, staging, session_id)
        staging.remove(session_id)


def staged_upload(workspace: Workspace, staging: StagingStore, session_id: str, row: str) -> Path:
    session = read_staging(workspace, staging, session_id)
    try:
        return upload_path(workspace, session, row)
    except KeyError as exc:
        raise StagedRowMissingError(row) from exc
