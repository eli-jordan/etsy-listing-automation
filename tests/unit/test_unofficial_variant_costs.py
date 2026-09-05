"""Pure parsing only -- no httpx. Network behaviour is covered by the
contract layer (tests/contract/test_unofficial_variant_costs.py)."""

from __future__ import annotations

import pytest

from etsy_listings.newcmd.unofficial_variant_costs import parse_variant_costs

REAL_SHAPED_PAYLOAD = {
    "total": 2,
    "data": [
        {
            "id": 148324,
            "options": [4802, 14],
            "available": True,
            "available_print_providers": ["Monster Digital", "Printify Choice"],
            "fulfillment": "locally_optimized",
            "regional_fulfillment": [],
            "status": "in-stock",
            "costs": [{"result": 1304, "result_subscription": 1127}],
        },
        {
            "id": 101424,
            "options": [3322, 20],
            "available": True,
            "available_print_providers": ["Printful"],
            "fulfillment": "locally_optimized",
            "regional_fulfillment": [],
            "status": "in-stock",
            "costs": [{"result": 2140, "result_subscription": 1850}],
        },
    ],
}


def test_parses_the_real_captured_shape() -> None:
    assert parse_variant_costs(REAL_SHAPED_PAYLOAD) == {148324: 1304, 101424: 2140}


@pytest.mark.parametrize(
    "bad_entry",
    [
        {"id": "not-an-int-but-unparseable", "costs": [{"result": 100}]},
        {"id": 1},  # no costs key at all
        {"id": 1, "costs": []},  # empty costs list
        {"id": 1, "costs": [{"no_result_key": 1}]},
        {"costs": [{"result": 100}]},  # no id key at all
    ],
)
def test_a_malformed_entry_is_skipped_not_fatal(bad_entry: dict) -> None:
    payload = {"data": [bad_entry, {"id": 2, "costs": [{"result": 500}]}]}
    assert parse_variant_costs(payload) == {2: 500}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": "not a list"},
        {"data": None},
        None,
        "not even a dict",
        {"no_data_key": []},
    ],
)
def test_whole_payload_garbage_returns_empty_not_raises(payload: object) -> None:
    assert parse_variant_costs(payload) == {}  # type: ignore[arg-type]
