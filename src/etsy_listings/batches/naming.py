"""Name allocation (A38; spec *Cleaning and editing names*).

One base name drives both ``listings/<name>/`` and ``designs/<name>.png``, so
a name is free only when it is free for both, and for every other row of the
batch. :func:`allocate` is the one rule; staging calls it for its preview and
confirmation calls it again under the listing's lock, because the preview can
go stale between the two.
"""

from __future__ import annotations

from collections.abc import Iterable


def allocate(base: str, taken: Iterable[str]) -> str:
    """``base``, or ``base-N`` for the smallest ``N >= 2`` that is free.

    ``taken`` is compared casefolded, as Windows compares the directory names
    these become -- ``Moss`` on disk takes ``moss``. The caller supplies the
    union: listing names, design stems, the other rows' names and the names
    already allocated in this batch."""
    folded = {name.casefold() for name in taken}
    if base.casefold() not in folded:
        return base
    suffix = 2
    while f"{base}-{suffix}".casefold() in folded:
        suffix += 1
    return f"{base}-{suffix}"
