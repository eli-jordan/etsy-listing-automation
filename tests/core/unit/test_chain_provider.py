"""The shared AI double, :class:`~tests.support.ai_runs.ChainProvider`: which
task it thinks it was given (T08).

It tells the chain's three tasks apart by the response schema they carry --
by what the schema says, not which object it is, so a provider task built
from a copied or re-parsed schema answers the same, and a schema it does
not know is refused rather than taken for the SEO task.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from etsy_listings.core.ai.brief import BRIEF_RESPONSE_SCHEMA
from etsy_listings.core.ai.market_queries import MARKET_QUERIES_RESPONSE_SCHEMA
from etsy_listings.core.ai.models import Deadline, ProviderTask
from etsy_listings.core.ai.prompt import RESPONSE_SCHEMA

from tests.support.ai_runs import ChainProvider, Task


def _task(schema: Mapping[str, object]) -> ProviderTask:
    return ProviderTask(prompt_text="p", response_schema=schema, design_image=Path("design.png"))


@pytest.mark.parametrize(
    ("schema", "kind", "answer_key"),
    [
        (BRIEF_RESPONSE_SCHEMA, "brief", "brief"),
        (MARKET_QUERIES_RESPONSE_SCHEMA, "queries", "queries"),
        (RESPONSE_SCHEMA, "seo", "titles"),
    ],
)
def test_a_copied_schema_is_the_same_task(
    schema: Mapping[str, object], kind: Task, answer_key: str
) -> None:
    provider = ChainProvider()

    result = provider.generate(
        _task(json.loads(json.dumps(schema))), Deadline.starting_now(seconds=5)
    )
    provider.generate(_task(copy.deepcopy(schema)), Deadline.starting_now(seconds=5))

    assert provider.calls == [kind, kind]
    assert answer_key in json.loads(result.raw_output)


def test_an_unknown_schema_is_refused_not_taken_for_seo() -> None:
    provider = ChainProvider()
    unknown = {"type": "object", "properties": {"verdict": {"type": "string"}}}

    with pytest.raises(AssertionError, match="unknown response schema"):
        provider.generate(_task(unknown), Deadline.starting_now(seconds=5))
    assert provider.calls == []
