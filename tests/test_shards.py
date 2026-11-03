"""CI's windows shards must run every test exactly once between them."""

from __future__ import annotations

import pytest

from tests.support.shards import Shard

NODE_IDS = [f"tests/core/unit/test_{n % 40}.py::test_case[{n}]" for n in range(3000)]


def test_every_test_belongs_to_exactly_one_of_the_shards() -> None:
    shards = [Shard(i, 3) for i in (1, 2, 3)]
    for node_id in NODE_IDS:
        assert sum(shard.owns(node_id) for shard in shards) == 1


def test_the_shards_are_roughly_even() -> None:
    sizes = [sum(Shard(i, 3).owns(n) for n in NODE_IDS) for i in (1, 2, 3)]
    assert max(sizes) - min(sizes) < len(NODE_IDS) * 0.05


def test_a_shard_reads_index_slash_count() -> None:
    assert Shard.parse("2/3") == Shard(2, 3)


@pytest.mark.parametrize("text", ["3", "0/3", "4/3", "a/3", "1/", "-1/3"])
def test_a_malformed_or_out_of_range_shard_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="--shard"):
        Shard.parse(text)
