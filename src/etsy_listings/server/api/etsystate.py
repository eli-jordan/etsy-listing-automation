"""Which of this workspace's listings Etsy considers published.

The one fact a listing's status needs that the workspace cannot answer for
itself: nothing this tool does ever activates a listing, so
"live" only ever becomes true because a human pressed publish in Shop Manager,
and the only way to find out is to ask.

Three things make asking cheap enough to do on every read:

* **One request, not one per listing.** ``listing_states`` batches, so the
  listings table costs a single round trip regardless of how many rows it has.
* **A short memo.** ``GET /api/listings/{name}`` is also what every autosave
  PATCH answers with, so an uncached lookup would put an Etsy round trip
  behind every keystroke burst in the editor. :data:`TTL_SECONDS` is the
  longest a listing published in another tab stays badged as ``deployed``;
  short enough not to be noticed, long enough that a burst of saves costs one
  request.
* **The table does not wait for a refresh.** Measured on an 18-listing shop,
  the round trip was ~0.7s of a ~1.7s table load, paid on most visits since
  they come more than :data:`TTL_SECONDS` apart. A caller that only *draws*
  states passes ``stale_ok``: an answer up to :data:`STALE_SECONDS` old is
  drawn at once while a fresh one is fetched behind it for the next read.
  Callers that *decide* on a state -- the published-deletion refusal, the
  editor -- leave it off and keep the strict TTL.

Failure is silence, deliberately. A workspace with no Etsy key pair, no
sign-in, or a shop the token cannot read is an ordinary state well short of
Phase 3 -- the listings page must still open, with every listing reported as
not-live, which is what :func:`~etsy_listings.core.engine.status.is_live_etsy_state`
already reads a missing state as. A *background* refresh that fails keeps the
answers it was refreshing instead: they are still the best known, and the next
read tries again.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from etsy_listings.core.clients.etsy.listings import EtsyListingClient
from etsy_listings.core.clients.etsy.tokens import EtsyAuthError, EtsyRefreshBusyError
from etsy_listings.core.clients.etsy.transport import EtsyApiError
from etsy_listings.core.config.secrets import MissingCredentialError
from etsy_listings.core.engine.status import is_live_etsy_state

TTL_SECONDS = 30.0
"""How long a fetched state is reused without asking again. See the module
docstring."""

STALE_SECONDS = 600.0
"""How old a state a ``stale_ok`` caller still draws while a fresh one is
fetched. Past this the table waits for Etsy, so a page opened after a long
gap never shows a badge from much longer ago than it would be noticed."""

Clock = Callable[[], float]

ClientFor = Callable[[Path], EtsyListingClient]
"""How to build the listing client that asks: ``app_state.clients``' factory."""

Background = Callable[[Callable[[], None]], None]
"""How a refresh is run behind the read that needed it: a daemon thread in a
real host, a list a test runs when it chooses."""

_cache: dict[int, tuple[float, str | None]] = {}
"""listing id -> (when fetched, Etsy ``state`` or ``None``). Process-wide
rather than per-request: one `ui` process serves one workspace, and the whole
point is that two requests a second apart share an answer. The raw state
is what delete/retire badges need (inactive vs expired vs sold_out);
:func:`live_listing_ids` still collapses it."""

_refreshing: set[int] = set()
"""Ids a background refresh is already asking about, so a table polled every
half second starts one refresh, not one per poll."""

_refreshing_lock = threading.Lock()


def _in_a_thread(work: Callable[[], None]) -> None:
    threading.Thread(target=work, name="etsy-states-refresh", daemon=True).start()


def etsy_states(  # noqa: PLR0913 -- every argument after client_for is a test seam or the stale_ok switch
    root: Path,
    listing_ids: Iterable[int],
    *,
    client_for: ClientFor,
    now: Clock = time.monotonic,
    stale_ok: bool = False,
    background: Background = _in_a_thread,
) -> dict[int, str | None]:
    """Each of ``listing_ids``' Etsy ``state``, or ``None`` when unknown.

    Ids still inside the memo are answered from it; the rest are fetched in
    one batch. An id Etsy does not answer for is cached as ``None`` like any
    other, so a listing deleted on Etsy does not re-ask every time the table
    is drawn. With ``stale_ok`` an answer older than the TTL but younger
    than :data:`STALE_SECONDS` is returned as it stands and refreshed by
    ``background`` -- unless an id has no usable answer at all, when the one
    round trip that must happen anyway refreshes the old ones too.
    """
    wanted = set(listing_ids)
    if not wanted:
        return {}
    moment = now()
    found = _remembered(wanted, moment, TTL_SECONDS)
    stale: set[int] = set()
    if stale_ok:
        usable = _remembered(wanted - found.keys(), moment, STALE_SECONDS)
        stale = set(usable)
        found |= usable
    missing = wanted - found.keys()
    if missing:
        found |= _ask_and_keep(client_for(root), missing | stale, moment)
    elif stale:
        _refresh_behind(root, stale, client_for=client_for, now=now, background=background)
    return found


def live_listing_ids(
    root: Path,
    listing_ids: Iterable[int],
    *,
    client_for: ClientFor,
    now: Clock = time.monotonic,
) -> set[int]:
    """Which of ``listing_ids`` Etsy reports as published."""
    return {
        i
        for i, state in etsy_states(root, listing_ids, client_for=client_for, now=now).items()
        if is_live_etsy_state(state)
    }


def _remembered(ids: set[int], moment: float, max_age: float) -> dict[int, str | None]:
    return {i: _cache[i][1] for i in ids if i in _cache and moment - _cache[i][0] < max_age}


def _ask_and_keep(
    client: EtsyListingClient, listing_ids: set[int], moment: float
) -> dict[int, str | None]:
    """Ask in the foreground, where a failure is remembered as "not live"
    like any other answer -- see the module docstring."""
    asked = sorted(listing_ids)
    states = _ask(client, asked)
    answers: dict[int, str | None] = dict.fromkeys(asked)
    if states is not None:
        answers |= states
    for listing_id, state in answers.items():
        _cache[listing_id] = (moment, state)
    return answers


def _refresh_behind(
    root: Path,
    listing_ids: set[int],
    *,
    client_for: ClientFor,
    now: Clock,
    background: Background,
) -> None:
    with _refreshing_lock:
        claimed = listing_ids - _refreshing
        _refreshing.update(claimed)
    if not claimed:
        return

    def refresh() -> None:
        try:
            asked = sorted(claimed)
            states = _ask(client_for(root), asked)
            if states is None:
                return
            moment = now()
            for listing_id in asked:
                _cache[listing_id] = (moment, states.get(listing_id))
        finally:
            with _refreshing_lock:
                _refreshing.difference_update(claimed)

    background(refresh)


def _ask(client: EtsyListingClient, listing_ids: list[int]) -> dict[int, str] | None:
    """Etsy's answer, or ``None`` when it could not be asked."""
    try:
        return client.listing_states(listing_ids)
    except (EtsyApiError, EtsyAuthError, EtsyRefreshBusyError, MissingCredentialError):
        return None


def forget() -> None:
    """Drop the memo. For tests, and for a caller that has just changed which
    workspace this process serves."""
    _cache.clear()
    with _refreshing_lock:
        _refreshing.clear()
