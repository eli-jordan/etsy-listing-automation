"""The Codex-then-Claude chain, one same-provider output repair, and the
shared 60-second request deadline (AI SEO implementation plan, PR4, item 3;
the "Timeout and retries" and "Provider adapters" decisions).

This is the "orchestration service" the runtime design diagram and
`ai/providers.py`'s own docstring describe: it owns retry classification,
fallback order, the shared deadline, and turning a provider's raw text into
a validated `SeoProposal` (via `ai/validation.py`) -- none of that is an
adapter's job. `generate_proposal` is the one entry point; it is driven
entirely against the `SeoProvider` protocol, so it works identically whether
handed `FakeSeoProvider` doubles (every test in this module) or the real
`CodexProvider`/`ClaudeProvider` adapters (PR5's job to wire together).

Classification summary (implementation plan, "Timeout and retries"):

- A :class:`~etsy_listings.ai.errors.ProviderUnavailableError` from the
  *first* call to a provider falls through to the next one in ``providers``.
- Any proposal-shape problem -- the raw text is not JSON, not an object, or
  fails `ai/validation.py.validate_proposal` -- counts as "malformed" and
  gets exactly one same-provider repair call, carrying every reason
  (`ai/models.py.RepairContext`). Nothing about *why* it was malformed
  changes that: a JSON decode failure and a hard-validation failure are
  repaired identically.
- Anything else -- the repaired response is still invalid, the repair call
  itself could not even reach the provider, an unrecognised process error,
  or the deadline expiring -- surfaces as "Try again"
  (:class:`~etsy_listings.ai.errors.SeoTryAgainError`). None of these retry
  a second provider; the settled plan only permits fallback on the first,
  recognised-unavailable failure.
- :class:`~etsy_listings.ai.errors.ProviderCancelledError` is never caught
  here -- it propagates as-is, since a cancelled request retains no result
  and is not a failure to report as "Try again".
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping, Sequence

from etsy_listings.ai.errors import (
    ProviderUnavailableError,
    SeoAllProvidersUnavailableError,
    SeoDeadlineExceededError,
    SeoTryAgainError,
)
from etsy_listings.ai.models import Deadline, RepairContext, SeoProposal, SeoRequest
from etsy_listings.ai.providers import SeoProvider
from etsy_listings.ai.validation import ProposalValidationError, validate_proposal

_DEFAULT_SECONDS = 60.0
"""The settled whole-request budget: provider call, one same-provider
repair, and the permitted Codex-to-Claude fallback all share this one
`Deadline` (implementation plan, "Timeout and retries")."""


class _Malformed(Exception):
    """Internal-only: a provider's raw output could not become a
    `SeoProposal`, for any reason -- not valid JSON, not a JSON object, or a
    hard-validation failure. Never escapes this module; every case it covers
    is repaired identically, so nothing downstream needs to distinguish
    them."""

    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons: tuple[str, ...] = tuple(reasons)
        super().__init__("; ".join(self.reasons))


def _decode_and_validate(raw_output: str) -> SeoProposal:
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise _Malformed((f"response was not valid JSON: {exc}",)) from exc
    if not isinstance(parsed, Mapping):
        raise _Malformed(("response: expected a JSON object",)) from None
    try:
        return validate_proposal(parsed)
    except ProposalValidationError as exc:
        raise _Malformed(exc.reasons) from exc


def _resolve(
    provider: SeoProvider,
    request: SeoRequest,
    deadline: Deadline,
    raw_output: str,
    provider_name: str,
    cancel_event: threading.Event | None,
) -> SeoProposal:
    try:
        return _decode_and_validate(raw_output)
    except _Malformed as first_error:
        if deadline.expired:
            raise SeoDeadlineExceededError(
                f"{provider_name}: the shared deadline expired before a same-provider "
                f"repair could be attempted"
            ) from first_error

        try:
            repaired = provider.generate(
                request,
                deadline,
                repair=RepairContext(prior_raw_output=raw_output, reasons=first_error.reasons),
                cancel_event=cancel_event,
            )
        except ProviderUnavailableError as repair_error:
            raise SeoTryAgainError(
                f"{provider_name} became unavailable during its repair attempt: {repair_error}"
            ) from repair_error

        try:
            return _decode_and_validate(repaired.raw_output)
        except _Malformed as second_error:
            raise SeoTryAgainError(
                f"{provider_name}: the repaired response was still invalid: {second_error}"
            ) from second_error


def generate_proposal(
    request: SeoRequest,
    providers: Sequence[SeoProvider],
    *,
    deadline: Deadline | None = None,
    seconds: float = _DEFAULT_SECONDS,
    cancel_event: threading.Event | None = None,
) -> SeoProposal:
    """Try ``providers`` in order -- Codex, then Claude, per the settled
    plan -- against ``request``, within one shared ``deadline`` (a fresh
    ``seconds``-second one is started if none is given).

    ``cancel_event`` is the one `threading.Event` the settled "Cancellation"
    decision describes: the browser leaving the editor or its connection
    closing (PR5's job to detect) sets it, and this is the single place that
    forwards it to whichever provider is currently running -- both real
    adapters (`ai/codex.py`, `ai/claude.py`) already pass it straight through
    to `ai/process.py.run_managed`, which is what actually kills the
    subprocess tree. Left `None`, generation is simply not cancellable,
    which is what every existing call site (and every `FakeSeoProvider` test)
    wants.

    Returns a validated `SeoProposal`, or raises: `SeoAllProvidersUnavailableError`
    if every provider answered with a recognised availability failure,
    `SeoDeadlineExceededError`/`SeoTryAgainError` for everything the settled
    plan surfaces as "Try again", or lets a
    `~etsy_listings.ai.errors.ProviderCancelledError` propagate untouched.
    """
    if deadline is None:
        deadline = Deadline.starting_now(seconds=seconds)

    unavailable_reasons: list[str] = []
    for provider in providers:
        if deadline.expired:
            raise SeoDeadlineExceededError(
                "the shared deadline expired before every configured provider could be tried"
            )
        try:
            raw = provider.generate(request, deadline, cancel_event=cancel_event)
        except ProviderUnavailableError as exc:
            unavailable_reasons.append(str(exc))
            continue
        return _resolve(provider, request, deadline, raw.raw_output, raw.provider, cancel_event)

    raise SeoAllProvidersUnavailableError(unavailable_reasons)
