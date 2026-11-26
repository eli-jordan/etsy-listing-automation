"""The etsy-research-proven-mockups skill's `fetch_listings.py --downloads`: a digital
download sample searched through the API rather than read from browser pages."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).parents[1] / ".claude/skills/etsy-research-proven-mockups/fetch_listings.py"


@pytest.fixture(scope="module")
def fetch() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fetch_listings", SCRIPT)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["fetch_listings"] = module
    spec.loader.exec_module(module)
    return module


class Response:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body

    def json(self) -> dict[str, Any]:
        return self.body


class Search:
    """Answers listings/active with one shirt and two downloads per query."""

    def __init__(self) -> None:
        self.asked: list[dict[str, str]] = []

    def get(self, path: str, params: list[tuple[str, str]]) -> Response:
        assert path == "/v3/application/listings/active"
        self.asked.append(dict(params))
        offset = len(self.asked) * 10
        return Response(
            {
                "results": [
                    {"listing_id": 1, "listing_type": "physical"},
                    {"listing_id": 2, "listing_type": "download"},
                    {"listing_id": offset, "listing_type": "download"},
                ]
            }
        )


def test_only_downloads_are_kept_with_the_queries_that_found_them(fetch: ModuleType) -> None:
    search = Search()

    found = fetch._search(search, ["kente png", "kente svg"])

    assert sorted(found) == [2, 10, 20]
    assert [hit["q"] for hit in found[2]["hits"]] == ["kente png", "kente svg"]
    assert found[20]["hits"] == [{"q": "kente svg", "filters": ["download"], "position": 2}]
    assert search.asked[0] == {"keywords": "kente png", "limit": "100", "sort_on": "score"}
