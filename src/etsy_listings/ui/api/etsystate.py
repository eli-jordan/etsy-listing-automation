"""Which of this workspace's listings Etsy considers published.

The one fact a listing's status needs that the workspace cannot answer for
itself: nothing this tool does ever activates a listing (PRD non-goal 1), so
"live" only ever becomes true because a human pressed publish in Shop Manager,
and the only way to find out is to ask.

Two things make asking cheap enough to do on every read:

* **One request, not one per listing.** ``listing_states`` batches, so the
  listings table costs a single round trip regardless of how many rows it has.
* **A short memo.** ``GET /api/listings/{name}`` is also what every autosave
  PATCH answers with, so an uncached lookup would put an Etsy round trip
  behind every keystroke burst in the editor. :data:`TTL_SECONDS` is the
  longest a listing published in another tab stays badged as ``deployed``;
  short enough not to be noticed, long enough that a burst of saves costs one
  request.

Failure is silence, deliberately. A workspace with no Etsy key pair, no
sign-in, or a shop the token cannot read is an ordinary state well short of
Phase 3 -- the listings page must still open, with every listing reported as
not-live, which is what :func:`~etsy_listings.engine.status.is_live_etsy_state`
already reads a missing state as.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from pathlib import Path

from etsy_listings import connections
from etsy_listings.clients.etsy.tokens import EtsyAuthError
from etsy_listings.clients.etsy.transport import EtsyApiError
from etsy_listings.config.secrets import MissingCredentialError
from etsy_listings.engine.status import is_live_etsy_state

TTL_SECONDS = 30.0
"""How long a fetched state is reused. See the module docstring."""

Clock = Callable[[], float]

_cache: dict[int, tuple[float, bool]] = {}
"""listing id -> (expiry, is-live). Process-wide rather than per-request: one
`ui` process serves one workspace, and the whole point is that two requests a
second apart share an answer."""


def live_listing_ids(
    root: Path, listing_ids: Iterable[int], *, now: Clock = time.monotonic
) -> set[int]:
    """Which of ``listing_ids`` Etsy reports as published.

    Ids still inside the memo are answered from it; the rest are fetched in
    one batch. An id Etsy does not answer for is cached as not-live like any
    other, so a listing deleted on Etsy does not re-ask every time the table
    is drawn.
    """
    wanted = set(listing_ids)
    if not wanted:
        return set()

    moment = now()
    live = {i for i in wanted if i in _cache and _cache[i][0] > moment and _cache[i][1]}
    stale = {i for i in wanted if i not in _cache or _cache[i][0] <= moment}
    if not stale:
        return live

    expiry = moment + TTL_SECONDS
    for listing_id, state in _fetch(root, sorted(stale)).items():
        _cache[listing_id] = (expiry, state)
        if state:
            live.add(listing_id)
    return live


def _fetch(root: Path, listing_ids: list[int]) -> dict[int, bool]:
    """``listing_id -> is-live`` for every id asked about, including the ones
    Etsy had no answer for -- see the module docstring on why a failure is
    reported as "not live" rather than raised."""
    absent = dict.fromkeys(listing_ids, False)
    client = connections.etsy_listing_client(root)
    if client is None:
        return absent
    try:
        states = client.listing_states(listing_ids)
    except (EtsyApiError, EtsyAuthError, MissingCredentialError):
        return absent
    return {**absent, **{i: is_live_etsy_state(s) for i, s in states.items()}}


def forget() -> None:
    """Drop the memo. For tests, and for a caller that has just changed which
    workspace this process serves."""
    _cache.clear()
