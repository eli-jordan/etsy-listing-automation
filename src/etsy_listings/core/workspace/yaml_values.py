"""Compare and three-way merge parsed YAML values, as a workspace reader sees them.

:mod:`.yaml_source` decides from these what to change; it then edits the text.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def plain(value: object) -> Any:
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def same(a: object, b: object) -> bool:
    """Equal as a reader sees them: key order ignored, but ``1``, ``1.0`` and
    ``True`` are three different values in a file."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        assert isinstance(b, dict)
        return a.keys() == b.keys() and all(same(a[key], b[key]) for key in a)
    if isinstance(a, list):
        assert isinstance(b, list)
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))
    return a == b


def merge(source: Any, before: Any, after: Any) -> Any:
    if same(before, after):
        return source
    if not all(isinstance(value, dict) for value in (source, before, after)):
        return after
    result = {key: value for key, value in source.items() if key in after or key not in before}
    for key, value in after.items():
        if not (key in before and same(before[key], value)):
            result = _merge_key(result, before, key, value, order=list(after))
    return result


def _merge_key(
    result: dict[Any, Any], before: dict[Any, Any], key: Any, value: Any, *, order: list[Any]
) -> dict[Any, Any]:
    """``result`` with ``key`` changed to ``value``: merged where the source
    still holds it, else placed by ``order``."""
    if key in before and key in result:
        result[key] = merge(result[key], before[key], value)
        return result
    return _insert_after_predecessor(result, key, value, order=order)


def _insert_after_predecessor(
    mapping: dict[Any, Any], key: Any, value: Any, *, order: list[Any]
) -> dict[Any, Any]:
    """``mapping`` with ``key`` placed after the nearest key that precedes it
    in ``order`` and is already present, else last."""
    if key in mapping:
        mapping[key] = value
        return mapping
    preceding = [other for other in order[: order.index(key)] if other in mapping]
    if not preceding:
        return {**mapping, key: value}
    result: dict[Any, Any] = {}
    for existing, item in mapping.items():
        result[existing] = item
        if existing == preceding[-1]:
            result[key] = value
    return result
