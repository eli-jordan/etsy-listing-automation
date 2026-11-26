from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Final

from etsy_listings.core.ai.models import ProviderTask
from etsy_listings.core.ai.prompt import build_task_prompt

QUERY_COUNT: Final = 3


@dataclass(frozen=True)
class MarketQueriesRequest:
    """The inputs one extraction is built from.

    ``garment_title`` is the garment profile's display title (for example
    *Unisex Heavy Cotton Tee*). It is how the model learns the item type
    whose buyer word ends every query; nothing else about the garment -- its
    brand, colours or materials -- helps a search find comparable listings,
    and each one is a way for a query to narrow to one seller's wording.
    """

    brief: str
    garment_title: str
    design_image: Path


@dataclass(frozen=True)
class MarketQueries:
    queries: tuple[str, str, str]


MARKET_QUERIES_RESPONSE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["queries"],
    "properties": {
        "queries": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": QUERY_COUNT,
            "maxItems": QUERY_COUNT,
        }
    },
}
"""Handed to a CLI's structured-output option, and hard-validated again by
:func:`validate_market_queries` whatever the CLI enforced -- the rule every
task's schema follows (`ai/prompt.py.RESPONSE_SCHEMA`)."""


class MarketQueriesValidationError(Exception):
    def __init__(self, *reasons: str) -> None:
        self.reasons: tuple[str, ...] = reasons
        super().__init__("; ".join(reasons))


def default_market_queries_prompt_text() -> str:
    return (
        resources.files("etsy_listings.core.ai.resources")
        .joinpath("market-queries.md")
        .read_text(encoding="utf-8")
    )


def build_market_queries_task(seller_prompt: str, request: MarketQueriesRequest) -> ProviderTask:
    context = {"listing": {"brief": request.brief, "garment": {"title": request.garment_title}}}
    return ProviderTask(
        prompt_text=build_task_prompt(seller_prompt, context, MARKET_QUERIES_RESPONSE_SCHEMA),
        response_schema=MARKET_QUERIES_RESPONSE_SCHEMA,
        design_image=request.design_image,
    )


def validate_market_queries(parsed: object) -> MarketQueries:
    """Hard-validate an already-JSON-decoded response: exactly three unique,
    non-empty queries.

    Whitespace is collapsed first, as a brief's is, and uniqueness ignores
    case, because Etsy's search does: ``Hiking Shirt`` and ``hiking shirt``
    are one search, and running it twice would spend a third of the market
    step's calls learning nothing.
    """
    if not isinstance(parsed, dict):
        raise MarketQueriesValidationError("response: expected a JSON object")
    value = parsed.get("queries")
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise MarketQueriesValidationError("queries: expected an array of strings")

    queries = [" ".join(item.split()) for item in value]
    reasons = _query_problems(queries)
    if reasons:
        raise MarketQueriesValidationError(*reasons)
    first, second, third = queries
    return MarketQueries((first, second, third))


def _query_problems(queries: list[str]) -> list[str]:
    reasons: list[str] = []
    if len(queries) != QUERY_COUNT:
        reasons.append(f"queries: expected exactly {QUERY_COUNT}, got {len(queries)}")
    if any(not query for query in queries):
        reasons.append("queries: every query must be non-empty")
    folded = [query.casefold() for query in queries if query]
    if len(set(folded)) != len(folded):
        reasons.append("queries: must be unique, ignoring case")
    return reasons
