"""A live, read-only Etsy market search through the public research interface."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from etsy_listings import connections
from etsy_listings.clients.etsy.transport import BASE_URL
from etsy_listings.market import research
from etsy_listings.workspace.workspace import Workspace

pytestmark = pytest.mark.e2e

QUERIES = ("retro sunset hiking shirt", "mountain sunset tee", "hiking gift shirt")


def test_live_market_research_scores_comparables_without_writing(
    etsy_market_workspace: Workspace,
) -> None:
    methods: list[str] = []
    with httpx.Client(
        base_url=BASE_URL,
        event_hooks={"request": [lambda request: methods.append(request.method)]},
    ) as http:
        client = connections.etsy_market_client(etsy_market_workspace.root, http=http)
        assert client is not None

        result = research(
            QUERIES,
            client,
            today=datetime.now(UTC),
            own_shop_id=etsy_market_workspace.defaults.etsy.shop_id,
        )

    assert methods, "the test must reach Etsy rather than an empty fixture"
    assert set(methods) == {"GET"}
    assert result.queries == QUERIES
    assert 1 <= result.scored <= 20
    assert result.found >= result.scored
    assert len(result.listings) == result.scored
    assert [listing.rank for listing in result.listings] == list(range(1, result.scored + 1))
    assert all(
        listing.listing_id > 0 and listing.url and listing.title for listing in result.listings
    )
    assert all(0 <= listing.score <= 100 for listing in result.listings)
