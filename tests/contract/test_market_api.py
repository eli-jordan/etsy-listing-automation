"""``GET /api/listings/{name}/market``: the listing's latest market snapshot,
which the top listings panel reads on mount (market-seo.md, *UI*;
implementation plan, PR 8)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from etsy_listings.ui.api.app import create_app
from etsy_listings.workspace.workspace import Workspace

from tests.support.ai_runs import TODAY, seed_snapshot
from tests.support.builders import FIXTURE_LISTING as LISTING

MARKET = f"/api/listings/{LISTING}/market"


@pytest.fixture
def client(workspace_root: Path) -> Iterator[TestClient]:
    workspace = Workspace.discover(root_override=workspace_root)
    with TestClient(create_app(workspace, seo_provider_factory=lambda _ws: [])) as c:
        yield c


def test_it_answers_with_the_snapshot_the_last_run_saved(
    workspace_root: Path, client: TestClient
) -> None:
    seed_snapshot(workspace_root, scored=2)

    response = client.get(MARKET)

    assert response.status_code == 200
    body = response.json()
    assert body["queries"] == [
        "retro sunset hiking shirt",
        "mountain sunset tee",
        "hiking gift shirt",
    ]
    assert (body["found"], body["scored"], body["empty"]) == (13, 2, False)
    assert body["searched_at"] == "2026-09-24T12:00:00Z"
    assert [p["phrase"] for p in body["phrases"]] == ["hiking shirt", "retro sunset"]
    first = body["listings"][0]
    assert first == {
        "listing_id": 1,
        "rank": 1,
        "score_raw": 0.89,
        "score": 89,
        "title": "Retro Sunset Hiking Shirt 1",
        "url": "https://www.etsy.com/listing/1/retro-sunset",
        "shop_id": 71,
        "shop_name": "TrailTees1",
        "own_shop": False,
        "thumbnail_url": None,
        "search_rank": 1,
        "reviews": 10,
        "favourites_per_day": 1.5,
        "views_per_day": 12.0,
        "shop_sales": 500,
        "shop_rating": 4.8,
        "tags": ["hiking shirt", "retro sunset"],
        "lead": "A retro sunset over the peaks.",
    }


def test_a_search_that_found_nothing_is_still_an_answer(
    workspace_root: Path, client: TestClient
) -> None:
    seed_snapshot(workspace_root, scored=0)

    body = client.get(MARKET).json()

    assert (body["empty"], body["listings"], body["phrases"]) == (True, [], [])


def test_it_404s_before_the_first_search(client: TestClient) -> None:
    response = client.get(MARKET)

    assert response.status_code == 404
    assert response.json() == {"detail": f"no market snapshot for {LISTING!r}"}


def test_it_404s_for_a_listing_that_does_not_exist(
    workspace_root: Path, client: TestClient
) -> None:
    seed_snapshot(workspace_root, "gone", searched_at=TODAY)

    response = client.get("/api/listings/gone/market")

    assert response.status_code == 404
    assert response.json() == {"detail": "no listing 'gone'"}


def test_a_damaged_snapshot_reads_as_none(workspace_root: Path, client: TestClient) -> None:
    """Derivable data: the next run rewrites it, so it is not an error."""
    workspace = Workspace.discover(root_override=workspace_root)
    path = workspace.market_snapshot_file(LISTING)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    assert client.get(MARKET).status_code == 404


def test_no_full_description_is_sent(workspace_root: Path, client: TestClient) -> None:
    """market-seo.md, *What the proposal sees*: the lead, never the whole
    description -- the panel shows what the model saw."""
    seed_snapshot(workspace_root, scored=1)

    listing = client.get(MARKET).json()["listings"][0]

    assert "description" not in listing
