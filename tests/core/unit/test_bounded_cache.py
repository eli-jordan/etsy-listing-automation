"""`BoundedCache`: a locked least-recently-used cache bounded by a total
size, where an item bigger than the whole budget is served but never kept."""

from __future__ import annotations

import sys
import threading
from collections.abc import Iterator

import pytest

from etsy_listings.core.bounded_cache import BoundedCache


def _bytes_cache(budget: int) -> BoundedCache[str, bytes]:
    return BoundedCache(budget, size=len)


def test_it_evicts_the_least_recently_used_once_the_bytes_exceed_the_budget() -> None:
    cache = _bytes_cache(10)
    cache.put("a", b"aaaa")
    cache.put("b", b"bbbb")
    assert cache.get("a") == b"aaaa"

    cache.put("c", b"cccc")

    assert cache.get("b") is None
    assert cache.get("a") == b"aaaa"
    assert cache.get("c") == b"cccc"
    assert cache.held == 8


def test_an_item_larger_than_the_budget_is_not_kept_and_evicts_nothing() -> None:
    cache = _bytes_cache(10)
    cache.put("a", b"aaaa")

    cache.put("huge", b"x" * 11)

    assert cache.get("huge") is None
    assert cache.get("a") == b"aaaa"
    assert cache.held == 4


def test_an_oversized_replacement_drops_the_old_value_for_that_key() -> None:
    cache = _bytes_cache(10)
    cache.put("a", b"aaaa")
    cache.put("b", b"bb")

    cache.put("a", b"x" * 11)

    assert cache.get("a") is None
    assert cache.get("b") == b"bb"
    assert cache.held == 2


def test_replacing_a_key_counts_only_its_new_size() -> None:
    cache = _bytes_cache(10)
    cache.put("a", b"aaaa")
    cache.put("b", b"bbbb")

    cache.put("a", b"aa")

    assert cache.held == 6
    assert cache.get("a") == b"aa"
    assert cache.get("b") == b"bbbb"


def test_discard_releases_the_entry_and_ignores_an_absent_key() -> None:
    cache = _bytes_cache(10)
    cache.put("a", b"aaaa")

    cache.discard("a")
    cache.discard("never")

    assert cache.get("a") is None
    assert cache.held == 0


def test_clear_empties_it() -> None:
    cache = _bytes_cache(10)
    cache.put("a", b"aaaa")

    cache.clear()

    assert cache.get("a") is None
    assert cache.held == 0


def test_get_or_compute_computes_once_then_serves_the_kept_value() -> None:
    cache = _bytes_cache(10)
    calls: list[str] = []

    def compute() -> bytes:
        calls.append("a")
        return b"aaaa"

    first = cache.get_or_compute("a", compute)
    second = cache.get_or_compute("a", compute)

    assert calls == ["a"]
    assert first is second


def test_get_or_compute_serves_an_oversized_value_without_keeping_it() -> None:
    cache = _bytes_cache(10)

    assert cache.get_or_compute("huge", lambda: b"x" * 11) == b"x" * 11
    assert cache.held == 0


def test_get_or_compute_returns_the_value_a_racing_caller_stored_first() -> None:
    cache = _bytes_cache(10)
    stored = b"aaaa"

    def compute() -> bytes:
        cache.put("a", stored)
        return b"AAAA"

    assert cache.get_or_compute("a", compute) is stored
    assert cache.held == 4


def test_without_a_size_function_it_counts_entries() -> None:
    cache: BoundedCache[int, str] = BoundedCache(2)
    for key in range(3):
        cache.put(key, "value")

    assert cache.get(0) is None
    assert cache.held == 2


def test_a_size_error_other_than_too_large_is_not_swallowed() -> None:
    cache: BoundedCache[str, int] = BoundedCache(10, size=lambda value: value)

    with pytest.raises(ValueError, match="non-negative"):
        cache.put("a", -1)


@pytest.fixture
def _frequent_switches() -> Iterator[None]:
    before = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    yield
    sys.setswitchinterval(before)


def _hammer(cache: BoundedCache[str, bytes], worker: int, start: threading.Barrier) -> None:
    start.wait()
    for index in range(500):
        cache.put(f"{worker}-{index % 40}", b"x" * (1 + index % 7))
        cache.get(f"{(worker + 1) % 8}-{index % 40}")


def _surviving(cache: BoundedCache[str, bytes]) -> list[bytes]:
    keys = (f"{worker}-{index}" for worker in range(8) for index in range(40))
    return [value for key in keys if (value := cache.get(key)) is not None]


@pytest.mark.usefixtures("_frequent_switches")
def test_concurrent_puts_keep_the_accounting_within_the_budget() -> None:
    cache = _bytes_cache(100)
    start = threading.Barrier(8)
    failures: list[BaseException] = []

    def run(worker: int) -> None:
        try:
            _hammer(cache, worker, start)
        except BaseException as exc:  # noqa: BLE001 -- surfaced in the main thread's assert
            failures.append(exc)

    threads = [threading.Thread(target=run, args=(worker,)) for worker in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert cache.held == sum(len(value) for value in _surviving(cache)) <= 100
