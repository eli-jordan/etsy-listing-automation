"""Which tests one CI shard runs (`pytest --shard 2/3`).

CI splits the windows leg across parallel jobs. A test belongs to the shard
its node id hashes to, so the split is the same in every process (each
xdist worker collects on its own and must agree with the controller) and
the slow files spread across the shards instead of landing together, as
splitting by file or by collection order would put them.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Shard:
    index: int
    """1-based, as written on the command line."""
    count: int

    @classmethod
    def parse(cls, text: str) -> Shard:
        """``"2/3"``: the second of three shards."""
        index, sep, count = text.partition("/")
        if not sep or not index.isdigit() or not count.isdigit():
            raise ValueError(f"--shard takes INDEX/COUNT, such as 2/3; got {text!r}")
        shard = cls(int(index), int(count))
        if not 1 <= shard.index <= shard.count:
            raise ValueError(f"--shard index must be between 1 and {shard.count}; got {text!r}")
        return shard

    def owns(self, node_id: str) -> bool:
        # crc32, not hash(): str hashes are salted per process.
        return zlib.crc32(node_id.encode()) % self.count == self.index - 1
