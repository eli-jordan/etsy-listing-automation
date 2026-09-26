"""The latest market research per listing, kept so the top listings panel
survives a reload (market-seo.md, *Cache*; implementation plan, PR 3)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from etsy_listings.market import MarketResult, PhraseScore, ScoredListing, market_block, snapshot
from etsy_listings.market.snapshot import MarketSnapshot
from etsy_listings.workspace.workspace import Workspace

SEARCHED_AT = datetime(2026, 9, 24, 12, 30, tzinfo=UTC)


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


def _listing(listing_id: int, rank: int) -> ScoredListing:
    return ScoredListing(
        listing_id=listing_id,
        rank=rank,
        score_raw=0.725,
        score=73,
        title="Retro Sunset Hiking Shirt",
        url=f"https://www.etsy.com/listing/{listing_id}",
        shop_id=77,
        shop_name="TrailTees",
        own_shop=False,
        thumbnail_url=None,
        search_rank=1,
        reviews=10,
        favourites_per_day=3.0,
        views_per_day=None,
        shop_sales=50,
        shop_rating=None,
        tags=("hiking shirt", "retro sunset"),
        lead="A retro sunset over the peaks.",
    )


def _result() -> MarketResult:
    return MarketResult(
        queries=("retro sunset hiking shirt", "mountain sunset tee", "hiking gift shirt"),
        found=58,
        scored=2,
        listings=(_listing(1, 1), _listing(2, 2)),
        phrases=(PhraseScore(phrase="hiking shirt", listings=2, score=1.0),),
        relaxed=False,
        empty=False,
    )


def _empty() -> MarketResult:
    return MarketResult(
        queries=("a", "b", "c"),
        found=0,
        scored=0,
        listings=(),
        phrases=(),
        relaxed=True,
        empty=True,
    )


def test_a_snapshot_carries_the_result_when_it_was_searched_and_the_block() -> None:
    result = _result()
    taken = MarketSnapshot.of(result, searched_at=SEARCHED_AT)

    assert taken.queries == result.queries
    assert (taken.found, taken.scored) == (58, 2)
    assert taken.listings == result.listings
    assert taken.phrases == result.phrases
    assert (taken.relaxed, taken.empty) == (False, False)
    assert taken.searched_at == SEARCHED_AT
    assert taken.block == market_block(result)
    assert taken.block.startswith("<<<MARKET")


def test_an_empty_result_snapshots_with_no_block() -> None:
    """Nothing comparable is still the latest answer, so it is kept -- with
    no block, since the proposal went ahead without market data."""
    taken = MarketSnapshot.of(_empty(), searched_at=SEARCHED_AT)
    assert taken.empty
    assert taken.block == ""


def test_a_saved_snapshot_loads_back_equal(workspace: Workspace) -> None:
    taken = MarketSnapshot.of(_result(), searched_at=SEARCHED_AT)

    snapshot.save(workspace, "take-a-hike", taken)

    assert snapshot.load(workspace, "take-a-hike") == taken
    assert workspace.market_snapshot_file("take-a-hike").is_file()


def test_saving_again_replaces_the_previous_snapshot(workspace: Workspace) -> None:
    snapshot.save(workspace, "take-a-hike", MarketSnapshot.of(_result(), searched_at=SEARCHED_AT))
    later = MarketSnapshot.of(_empty(), searched_at=datetime(2026, 9, 25, tzinfo=UTC))

    snapshot.save(workspace, "take-a-hike", later)

    assert snapshot.load(workspace, "take-a-hike") == later


def test_a_listing_with_no_snapshot_loads_none(workspace: Workspace) -> None:
    assert snapshot.load(workspace, "take-a-hike") is None


@pytest.mark.parametrize(
    "text",
    ["", "{truncated", "[]", json.dumps({"queries": ["a"]})],
    ids=["empty", "not-json", "not-an-object", "wrong-shape"],
)
def test_a_corrupt_snapshot_loads_none(workspace: Workspace, text: str) -> None:
    path = workspace.market_snapshot_file("take-a-hike")
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")

    assert snapshot.load(workspace, "take-a-hike") is None


def test_a_failed_write_leaves_the_previous_snapshot_whole(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Atomic: the new snapshot is written beside the old one and swapped in,
    so a crash mid-write never leaves a half file where the panel reads."""
    before = MarketSnapshot.of(_result(), searched_at=SEARCHED_AT)
    snapshot.save(workspace, "take-a-hike", before)

    def crash(source: object, destination: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(OSError, match="disk full"):
        snapshot.save(
            workspace, "take-a-hike", MarketSnapshot.of(_empty(), searched_at=SEARCHED_AT)
        )
    monkeypatch.undo()

    assert snapshot.load(workspace, "take-a-hike") == before
    siblings = list(workspace.market_snapshot_file("take-a-hike").parent.iterdir())
    assert [p.name for p in siblings] == ["take-a-hike.json"]
