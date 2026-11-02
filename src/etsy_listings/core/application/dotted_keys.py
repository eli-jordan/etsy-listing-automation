"""Dotted keys into a YAML document, shared by the Admin page's two files
(``shop_settings`` and ``workspace_settings``)."""

from __future__ import annotations

from typing import Any


def parent_of(document: dict[str, Any], key: str) -> tuple[dict[str, Any], str]:
    """The mapping that holds ``key``'s last part, and that part.

    A missing parent, or one that is not a mapping, is replaced by an empty
    mapping on the way down: the edit owns that branch from here.
    """
    *parents, leaf = key.split(".")
    node = document
    for part in parents:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    return node, leaf
