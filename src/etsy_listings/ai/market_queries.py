"""Query extraction (market-seo.md, *Query extraction*; PRD 71): the request
shape, the packaged default `prompts/market-queries.md`, the response schema,
and the validation three buyer search queries pass before market search
spends Etsy calls on them.

One module for the same reason `ai/brief.py` is one: a small contract, and
everything around it -- the delimited-context wrapper, the provider chain,
the repair and the deadline -- is already owned elsewhere. A query request is
an ordinary `ai/models.py.ProviderTask`.

Validation checks exactly what the spec says and no more: three unique,
non-empty queries. The prompt asks for each query to end in the buyer's word
for the item type (the job a taxonomy filter would otherwise do), but a
model that writes ``retro sunset hiking tees`` or ``hiking t shirt`` has
still written a usable search, and refusing it would spend the one repair on
a matter of wording.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Final

from etsy_listings.ai.models import ProviderTask
from etsy_listings.ai.prompt import build_task_prompt

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
    """Three validated buyer search queries, in the model's order."""

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
    """A response could not become `MarketQueries`. Carries every reason, so
    the one repair attempt hears them all (`ai/brief.py.BriefValidationError`)."""

    def __init__(self, *reasons: str) -> None:
        self.reasons: tuple[str, ...] = reasons
        super().__init__("; ".join(reasons))


def default_market_queries_prompt_text() -> str:
    """The packaged default ``prompts/market-queries.md``, read fresh each
    call like the other two packaged prompts."""
    return (
        resources.files("etsy_listings.ai.resources")
        .joinpath("market-queries.md")
        .read_text(encoding="utf-8")
    )


def build_market_queries_task(seller_prompt: str, request: MarketQueriesRequest) -> ProviderTask:
    """One extraction, as the thing a provider adapter runs."""
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
    reasons: list[str] = []
    if len(queries) != QUERY_COUNT:
        reasons.append(f"queries: expected exactly {QUERY_COUNT}, got {len(queries)}")
    if any(not query for query in queries):
        reasons.append("queries: every query must be non-empty")
    folded = [query.casefold() for query in queries if query]
    if len(set(folded)) != len(folded):
        reasons.append("queries: must be unique, ignoring case")
    if reasons:
        raise MarketQueriesValidationError(*reasons)
    first, second, third = queries
    return MarketQueries((first, second, third))
