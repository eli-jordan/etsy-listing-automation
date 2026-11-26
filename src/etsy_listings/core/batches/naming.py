from __future__ import annotations

from collections.abc import Iterable


def allocate(base: str, taken: Iterable[str]) -> str:
    folded = {name.casefold() for name in taken}
    if base.casefold() not in folded:
        return base
    suffix = 2
    while f"{base}-{suffix}".casefold() in folded:
        suffix += 1
    return f"{base}-{suffix}"
