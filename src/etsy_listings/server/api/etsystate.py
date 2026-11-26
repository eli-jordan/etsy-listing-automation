"""Which of this workspace's listings Etsy considers published, asked in one
batched request and memoised for :data:`TTL_SECONDS`.

Failure is silence: with no key pair, no sign-in or an unreadable shop every
listing reads as not live, and a failed background refresh keeps the answers it
was refreshing."""

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
"""How long a fetched state is reused without asking again: the longest a
listing published in another tab stays badged ``deployed``, and long enough
that a burst of autosaves costs one Etsy request."""

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

    Unmemoised ids are fetched in one batch. With ``stale_ok``, an answer past
    the TTL but within :data:`STALE_SECONDS` is returned and refreshed by
    ``background``; only a caller that draws states, never one that decides on
    one, passes it.
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
