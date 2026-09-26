"""``settings.yaml``: the workspace's tunable settings, today only the market
scoring weights (market-seo.md, *Scoring*; implementation plan, PR 3).

A missing file or key falls back to the spec's defaults. Anything present
but wrong fails naming the file and the key.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.config.errors import ConfigLoadError
from etsy_listings.market import MarketWeights
from etsy_listings.workspace.workspace import Workspace

SPEC_DEFAULTS = {
    "reviews": 30,
    "favourites_per_day": 30,
    "search_rank": 20,
    "views_per_day": 10,
    "shop_sales": 5,
    "shop_rating": 5,
}


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


def _write(workspace: Workspace, text: str) -> Path:
    path = workspace.root / "settings.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _weights(workspace: Workspace) -> dict[str, float]:
    return workspace.load_settings().market_seo.weights.model_dump()


def test_the_file_sits_next_to_shop_yaml(workspace: Workspace) -> None:
    assert workspace.settings_file() == workspace.root / "settings.yaml"


def test_a_missing_file_gives_the_spec_defaults(workspace: Workspace) -> None:
    assert not workspace.settings_file().exists()
    assert _weights(workspace) == SPEC_DEFAULTS
    assert workspace.load_settings().market_seo.weights == MarketWeights()


@pytest.mark.parametrize(
    "text",
    ["", "# nothing tuned yet\n", "market_seo:\n", "market_seo:\n  weights:\n"],
    ids=["empty", "comment-only", "empty-section", "empty-weights"],
)
def test_an_empty_file_or_section_gives_the_spec_defaults(workspace: Workspace, text: str) -> None:
    _write(workspace, text)
    assert _weights(workspace) == SPEC_DEFAULTS


def test_a_partial_weights_block_keeps_the_defaults_for_missing_keys(
    workspace: Workspace,
) -> None:
    _write(workspace, "market_seo:\n  weights:\n    reviews: 50\n    shop_rating: 0\n")
    assert _weights(workspace) == SPEC_DEFAULTS | {"reviews": 50, "shop_rating": 0}


def test_the_spec_example_loads_as_written(workspace: Workspace) -> None:
    _write(
        workspace,
        """market_seo:
  weights:
    reviews: 30
    favourites_per_day: 30
    search_rank: 20
    views_per_day: 10
    shop_sales: 5
    shop_rating: 5
""",
    )
    assert _weights(workspace) == SPEC_DEFAULTS


def test_edits_are_read_on_the_next_load(workspace: Workspace) -> None:
    """Read when asked, not at discovery: a seller tuning weights with the
    UI running sees the next research use them, and a broken file breaks
    only what reads it."""
    assert _weights(workspace)["reviews"] == 30
    _write(workspace, "market_seo:\n  weights:\n    reviews: 12.5\n")
    assert _weights(workspace)["reviews"] == 12.5


@pytest.mark.parametrize(
    ("text", "key", "message"),
    [
        ("market_seo:\n  weights:\n    reviews: -1\n", "market_seo.weights.reviews", "greater"),
        ("market_seo:\n  weights:\n    reviews: lots\n", "market_seo.weights.reviews", "number"),
        (
            "market_seo:\n  weights:\n    review: 30\n",
            "market_seo.weights.review",
            "not permitted",
        ),
        ("market-seo:\n  weights: {}\n", "market-seo", "not permitted"),
        ("market_seo:\n  weight: {}\n", "market_seo.weight", "not permitted"),
        ("market_seo:\n  weights: [30, 30]\n", "market_seo.weights", "dictionary"),
        (
            "market_seo:\n  weights:\n"
            "    reviews: 0\n    favourites_per_day: 0\n    search_rank: 0\n"
            "    views_per_day: 0\n    shop_sales: 0\n    shop_rating: 0\n",
            "market_seo.weights",
            "at least one market_seo weight must be above zero",
        ),
    ],
    ids=[
        "negative",
        "not-a-number",
        "unknown-weight",
        "unknown-section",
        "unknown-market-seo-key",
        "weights-not-a-mapping",
        "all-zero",
    ],
)
def test_an_invalid_value_names_the_file_and_the_key(
    workspace: Workspace, text: str, key: str, message: str
) -> None:
    path = _write(workspace, text)

    with pytest.raises(ConfigLoadError) as caught:
        workspace.load_settings()

    assert str(path) in str(caught.value)
    assert f"{key}:" in str(caught.value)
    assert message in str(caught.value)


@pytest.mark.parametrize(
    "text",
    ["market_seo: [\n", "- just\n- a list\n", "42\n"],
    ids=["bad-yaml", "a-list", "a-scalar"],
)
def test_a_file_that_is_not_a_mapping_names_the_file(workspace: Workspace, text: str) -> None:
    path = _write(workspace, text)

    with pytest.raises(ConfigLoadError) as caught:
        workspace.load_settings()

    assert str(path) in str(caught.value)
