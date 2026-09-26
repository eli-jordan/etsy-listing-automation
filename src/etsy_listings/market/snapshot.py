"""The latest market research per listing, on disk (market-seo.md, *Cache*).

``.cache/market/snapshots/{name}.json`` exists so the top listings panel can
show a listing's comparables after a reload. It is written only by a run
whose research **succeeded** -- a failed run leaves the previous one in place,
while a search that found nothing comparable replaces it, because that *is*
the latest answer. It moves with the listing on rename and goes when the
listing is deleted, as ``.cache/renders/{name}/`` does; both are the
listings API's (and :meth:`Workspace.remove_listing`'s) job, not this
module's.

Read-only to the seller in this version: nothing edits a snapshot but the
next research.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, ValidationError

from etsy_listings.market.block import market_block
from etsy_listings.market.models import MarketResult, PhraseScore, ScoredListing
from etsy_listings.workspace.workspace import Workspace


class MarketSnapshot(BaseModel):
    """One research, as the panel reads it back: the result's fields, when
    the search ran, and the exact block the proposal was given. Holds each
    listing's lead, never its full description (market-seo.md, *What the
    proposal sees*)."""

    model_config = ConfigDict(frozen=True)

    queries: tuple[str, ...]
    found: int
    scored: int
    searched_at: datetime
    listings: tuple[ScoredListing, ...]
    phrases: tuple[PhraseScore, ...]
    relaxed: bool
    empty: bool
    block: str
    """What :func:`~etsy_listings.market.block.market_block` gave the
    proposal: ``""`` for an empty result."""

    @classmethod
    def of(cls, result: MarketResult, *, searched_at: datetime) -> MarketSnapshot:
        return cls(
            queries=result.queries,
            found=result.found,
            scored=result.scored,
            searched_at=searched_at,
            listings=result.listings,
            phrases=result.phrases,
            relaxed=result.relaxed,
            empty=result.empty,
            block=market_block(result),
        )


def save(workspace: Workspace, name: str, snapshot: MarketSnapshot) -> None:
    """Replace ``name``'s snapshot atomically: written beside the old file
    and swapped in, so a reader sees the old snapshot or the new one, never
    half of either."""
    path = workspace.market_snapshot_file(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def load(workspace: Workspace, name: str) -> MarketSnapshot | None:
    """``name``'s snapshot, or ``None`` when it has none -- or only a file
    that no longer reads as one. The snapshot is derivable (the next run
    rewrites it), so a damaged one is shown as no snapshot, not an error."""
    path = workspace.market_snapshot_file(name)
    try:
        return MarketSnapshot.model_validate_json(path.read_bytes())
    except (OSError, ValidationError):
        return None
