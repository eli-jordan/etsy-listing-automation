"""Query extraction (market-seo.md, *Query extraction*): the provider call that
turns a brief, a design and the garment's display title into three buyer
search queries.

Driven through `generate_market_queries` against `FakeAiProvider`, the seam
the AI run (PR 5) calls. It is `run_task` under its own decoder, so what is
worth asserting is what differs from the other two tasks -- the task a
provider is handed and the validation rule -- plus one pass through each of
the shared behaviours (fallback, repair) to prove the decoder is wired into
them rather than beside them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from etsy_listings.ai.errors import ProviderUnavailableError, SeoTryAgainError
from etsy_listings.ai.market_queries import (
    MarketQueries,
    MarketQueriesRequest,
    MarketQueriesValidationError,
    build_market_queries_task,
    validate_market_queries,
)
from etsy_listings.ai.models import Deadline, ProviderTask, RawProviderResult, RepairContext
from etsy_listings.ai.orchestrator import generate_market_queries
from etsy_listings.ai.providers import FakeAiProvider

PROMPT = "Write three queries.\n"


def _request() -> MarketQueriesRequest:
    return MarketQueriesRequest(
        brief="Retro 70s sunset over mountains; the text reads TAKE A HIKE.",
        garment_title="Unisex Heavy Cotton Tee",
        design_image=Path("designs/take-a-hike.png"),
    )


def _answer(*queries: object) -> str:
    return json.dumps({"queries": list(queries)})


def _generate(*responses: str) -> tuple[MarketQueries, FakeAiProvider]:
    codex = FakeAiProvider(name="codex", responses=list(responses))
    return generate_market_queries(_request(), PROMPT, [codex]), codex


def test_three_queries_come_back_in_the_order_the_model_gave_them() -> None:
    queries, codex = _generate(
        _answer("retro sunset hiking shirt", "take a hike tee", "mountain sunset shirt")
    )

    assert queries == MarketQueries(
        ("retro sunset hiking shirt", "take a hike tee", "mountain sunset shirt")
    )
    assert codex.tasks == [build_market_queries_task(PROMPT, _request())]


def test_surrounding_and_repeated_whitespace_is_not_worth_a_repair() -> None:
    queries, codex = _generate(_answer("  retro  sunset shirt ", "hiking\ttee", "mountain shirt"))

    assert queries.queries == ("retro sunset shirt", "hiking tee", "mountain shirt")
    assert codex.repairs == [None]


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        (_answer("retro shirt", "hiking tee"), "expected exactly 3, got 2"),
        (_answer("a shirt", "b shirt", "c shirt", "d shirt"), "expected exactly 3, got 4"),
        (_answer("retro shirt", "   ", "hiking tee"), "every query must be non-empty"),
        (_answer("Hiking Shirt", "hiking  shirt", "retro tee"), "must be unique, ignoring case"),
        (_answer("retro shirt", 7, "hiking tee"), "expected an array of strings"),
        (json.dumps({"queries": "retro shirt"}), "expected an array of strings"),
        (json.dumps({"query": ["a", "b", "c"]}), "expected an array of strings"),
        ('["a", "b", "c"]', "expected a JSON object"),
        ("retro shirt, hiking tee", "not valid JSON"),
    ],
)
def test_a_response_that_is_not_three_usable_queries_is_repaired_once(
    bad: str, reason: str
) -> None:
    good = _answer("retro sunset shirt", "take a hike tee", "mountain shirt")

    queries, codex = _generate(bad, good)

    assert queries.queries == ("retro sunset shirt", "take a hike tee", "mountain shirt")
    repair = codex.repairs[1]
    assert repair is not None
    assert repair.prior_raw_output == bad
    assert any(reason in r for r in repair.reasons), repair.reasons


def test_every_reason_reaches_the_repair_at_once() -> None:
    _, codex = _generate(_answer("", "tee", "TEE", "shirt"), _answer("a tee", "b tee", "c tee"))

    reasons = codex.repairs[1].reasons  # type: ignore[union-attr]
    assert len(reasons) == 3


def test_queries_still_unusable_after_the_repair_fail_as_try_again() -> None:
    with pytest.raises(SeoTryAgainError):
        _generate(_answer("one shirt"), _answer("one shirt", "one shirt", "one shirt"))


def test_an_unavailable_first_provider_falls_through_to_the_second() -> None:
    class _SignedOut(FakeAiProvider):
        def generate(
            self,
            task: ProviderTask,
            deadline: Deadline,
            *,
            repair: RepairContext | None = None,
            cancel_event: object = None,
        ) -> RawProviderResult:
            raise ProviderUnavailableError("codex", "not signed in")

    claude = FakeAiProvider(name="claude", responses=[_answer("a shirt", "b tee", "c shirt")])

    queries = generate_market_queries(_request(), PROMPT, [_SignedOut(name="codex"), claude])

    assert queries.queries == ("a shirt", "b tee", "c shirt")
    assert claude.tasks == [build_market_queries_task(PROMPT, _request())]


def test_validation_refuses_anything_but_an_object_on_its_own() -> None:
    """The orchestrator refuses a non-object before this runs; the AI run
    (PR 5) is free to call the validator directly, so it holds the rule too."""
    with pytest.raises(MarketQueriesValidationError, match="expected a JSON object"):
        validate_market_queries(["a shirt", "b shirt", "c shirt"])
