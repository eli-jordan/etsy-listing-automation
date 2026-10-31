"""``settings.yaml``: the workspace's tunable settings, today only the market
scoring weights (features/market-seo-20260924/spec.md, *Scoring*; implementation plan, PR 3).

A missing file or key falls back to the spec's defaults. Anything present
but wrong fails naming the file and the key.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.core.config import MarketWeights
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.workspace.workspace import Workspace

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


class TestBatchAi:
    """``batch_ai.concurrency``: how many batch rows draft at once, across
    every batch (spec, *Batch AI queue*; ADR-0048), from 1 to 8 (Admin plan,
    *Settings*: the Admin page's slider covers the whole range)."""

    def test_the_default_is_one_at_a_time(self, workspace: Workspace) -> None:
        assert workspace.load_settings().batch_ai.concurrency == 1

    @pytest.mark.parametrize("text", ["batch_ai:\n", "market_seo:\n  weights:\n"])
    def test_an_empty_section_is_the_default(self, workspace: Workspace, text: str) -> None:
        _write(workspace, text)
        assert workspace.load_settings().batch_ai.concurrency == 1

    def test_the_limit_is_read_from_the_file(self, workspace: Workspace) -> None:
        _write(workspace, "batch_ai:\n  concurrency: 3\n")
        assert workspace.load_settings().batch_ai.concurrency == 3

    def test_eight_is_the_highest_limit(self, workspace: Workspace) -> None:
        _write(workspace, "batch_ai:\n  concurrency: 8\n")
        assert workspace.load_settings().batch_ai.concurrency == 8

    @pytest.mark.parametrize(
        ("text", "key"),
        [
            ("batch_ai:\n  concurrency: 0\n", "batch_ai.concurrency"),
            ("batch_ai:\n  concurrency: 9\n", "batch_ai.concurrency"),
            ("batch_ai:\n  concurrency: 2.5\n", "batch_ai.concurrency"),
            ("batch_ai:\n  concurency: 2\n", "batch_ai.concurency"),
        ],
        ids=["zero", "above-eight", "fractional", "misspelt"],
    )
    def test_an_invalid_limit_names_the_key(
        self, workspace: Workspace, text: str, key: str
    ) -> None:
        _write(workspace, text)

        with pytest.raises(ConfigLoadError) as caught:
            workspace.load_settings()

        assert f"{key}:" in str(caught.value)


def test_ai_defaults_and_ordered_preferences(workspace: Workspace) -> None:
    assert [p.name for p in workspace.load_settings().ai.providers] == ["codex", "claude", "grok"]
    _write(
        workspace,
        "ai:\n  providers:\n    - name: grok\n      model: retired-model\n"
        "      effort: retired-effort\n    - name: codex\n      enabled: false\n",
    )
    providers = workspace.load_settings().ai.providers
    assert [(p.name, p.enabled, p.model, p.effort) for p in providers] == [
        ("grok", True, "retired-model", "retired-effort"),
        ("codex", False, None, None),
    ]


@pytest.mark.parametrize(
    ("yaml", "key"),
    [
        ("providers: []", "ai.providers"),
        ("providers: [{name: codex, enabled: false}]", "ai.providers"),
        ("providers: [{name: codex}, {name: codex}]", "ai.providers"),
        ("providers: [{name: unknown}]", "ai.providers.0.name"),
        ("providers: [{name: codex, tier: fast}]", "ai.providers.0.tier"),
        ("provider: []", "ai.provider"),
    ],
)
def test_ai_refusals_name_file_and_dotted_key(workspace: Workspace, yaml: str, key: str) -> None:
    path = _write(workspace, "ai:\n  " + yaml + "\n")
    with pytest.raises(ConfigLoadError) as caught:
        workspace.load_settings()
    assert str(path) in str(caught.value)
    assert key + ":" in str(caught.value)
