"""The assembled text each provider call is handed, against golden files
(market-seo-implementation-plan.md, PR 4): the query-extraction prompt, and
the proposal prompt with and without a market block.

A short stand-in replaces the seller's prompt file, so these goldens pin the
*assembly* -- which blocks appear, in what order, inside which delimiters --
and do not churn every time the packaged prose is edited. What the packaged
prompts say is `tests/unit/test_ai_packaged_prompts.py`'s subject.

Regenerate with ``--update-goldens`` after reading the diff.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.ai.market_queries import MarketQueriesRequest, build_market_queries_task
from etsy_listings.ai.models import GarmentContext, SeoRequest
from etsy_listings.ai.prompt import build_seo_task
from etsy_listings.market import MARKET_BEGIN, MARKET_END

GOLDENS = Path(__file__).parent / "ai"
SELLER_PROMPT = "The seller's own instructions.\n"
BLOCK = f'{MARKET_BEGIN}\n{{\n  "ranked_phrases": []\n}}\n{MARKET_END}\n'
"""Stands in for `market.market_block()`'s output, whose own golden is
`market/market_block.txt`: this file only cares where the block lands."""


def _seo_request(market_block: str = "") -> SeoRequest:
    return SeoRequest(
        brief="Retro 70s sunset over mountains; the text reads TAKE A HIKE.",
        product_type="Unisex Heavy Cotton Tee",
        etsy_category="Clothing > Unisex Adult Clothing > Tops & Tees > T-shirts",
        materials=("cotton",),
        colors=("Black", "Natural"),
        garment=GarmentContext(brand="Gildan", model="5000"),
        design_image=Path("designs/take-a-hike.png"),
        market_block=market_block,
    )


def _check(name: str, actual: str, update_goldens: bool) -> None:
    golden = GOLDENS / name
    if update_goldens or not golden.is_file():
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(actual, encoding="utf-8", newline="\n")
        if not update_goldens:
            pytest.fail(f"no golden at {golden} -- wrote one. Review it, then re-run.")
        return
    assert actual == golden.read_text(encoding="utf-8")


def test_the_query_extraction_prompt(update_goldens: bool) -> None:
    task = build_market_queries_task(
        SELLER_PROMPT,
        MarketQueriesRequest(
            brief="Retro 70s sunset over mountains; the text reads TAKE A HIKE.",
            garment_title="Unisex Heavy Cotton Tee",
            design_image=Path("designs/take-a-hike.png"),
        ),
    )
    _check("market_queries_prompt.txt", task.prompt_text, update_goldens)


def test_the_proposal_prompt_without_market_data(update_goldens: bool) -> None:
    task = build_seo_task(SELLER_PROMPT, _seo_request())
    assert MARKET_BEGIN not in task.prompt_text
    _check("seo_prompt.txt", task.prompt_text, update_goldens)


def test_the_proposal_prompt_with_market_data(update_goldens: bool) -> None:
    task = build_seo_task(SELLER_PROMPT, _seo_request(BLOCK))
    _check("seo_prompt_with_market.txt", task.prompt_text, update_goldens)


def test_the_market_block_sits_after_the_listing_and_before_the_schema() -> None:
    """The listing context first, as the data the claims come from; then the
    market data; then the contract the answer must meet, last, where a model
    reads it just before it starts writing."""
    text = build_seo_task(SELLER_PROMPT, _seo_request(BLOCK)).prompt_text

    listing = text.index("<<<END_LISTING_CONTEXT_JSON>>>")
    market = text.index(MARKET_BEGIN)
    schema = text.index("<<<RESPONSE_JSON_SCHEMA>>>")
    assert listing < market < schema
    assert text.count(MARKET_BEGIN) == 1
