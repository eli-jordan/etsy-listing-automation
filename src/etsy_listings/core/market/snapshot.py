from __future__ import annotations

import contextlib
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, ValidationError

from etsy_listings.core.market.block import market_block
from etsy_listings.core.market.models import MarketResult, PhraseScore, ScoredListing
from etsy_listings.core.workspace.workspace import Workspace


class MarketSnapshot(BaseModel):
    """One listing's latest market research, as the top listings panel reads it back."""

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
    """What :func:`~etsy_listings.core.market.block.market_block` gave the
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
        temporary.replace(path)
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
