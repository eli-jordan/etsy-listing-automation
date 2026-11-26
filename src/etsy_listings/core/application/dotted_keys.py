from __future__ import annotations

from typing import Any


def parent_of(document: dict[str, Any], key: str) -> tuple[dict[str, Any], str]:
    """The mapping that holds ``key``'s last part, and that part, creating
    or replacing any parent on the way that is not a mapping."""
    *parents, leaf = key.split(".")
    node = document
    for part in parents:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    return node, leaf
