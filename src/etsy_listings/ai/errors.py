"""The exception hierarchy `ai/orchestrator.py`'s Codex-to-Claude chain and
both CLI adapters (`ai/codex.py`, `ai/claude.py`) share, plus
:func:`classify_process_failure` -- the one place a nonzero-exit CLI process
is sorted into "provider unavailable" versus everything else (AI SEO
implementation plan, "Timeout and retries": "Only recognised
provider-unavailable, authentication-quota, or rate-limit failures fall
through to Claude. Other failures show **Try again**.").

Every exception here is a :class:`SeoGenerationError`. `ai/orchestrator.py`
only ever special-cases two of its subclasses -- :class:`ProviderUnavailableError`
(catch it, fall through to the next provider) and :class:`ProviderCancelledError`
(let it propagate untouched, since a cancelled request retains no result and
is not a failure to report as "Try again"). Every other subclass, including
ones an adapter raises directly, already reads as "Try again" simply by being
a :class:`SeoTryAgainError` -- the orchestrator does not need to know about
:class:`ProviderTimeoutError` or :class:`ProviderGenerationError` by name for
that to be true.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any


class SeoGenerationError(RuntimeError):
    """Base for every error one AI Mode SEO request can end in."""


class ProviderUnavailableError(SeoGenerationError):
    """A recognised provider-unavailable, authentication, quota, or
    rate-limit failure -- the one category the settled plan permits to fall
    through to the next provider in the Codex-then-Claude chain."""

    def __init__(self, provider: str, reason: str) -> None:
        self.provider = provider
        self.reason = reason
        super().__init__(f"{provider}: {reason}")


class ProviderCancelledError(SeoGenerationError):
    """The request was aborted -- the editor was left, or the browser
    connection closed -- before a result was produced (implementation plan,
    "Cancellation"). No proposal is retained; this is not shown as a
    failure, so it is deliberately not a :class:`SeoTryAgainError`."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(f"{provider}: request was cancelled")


class SeoTryAgainError(SeoGenerationError):
    """Every failure the settled plan says surfaces as **Try again**: a
    validation failure that survived the one same-provider repair, an
    unrecognised process error, or the shared deadline expiring."""


class SeoDeadlineExceededError(SeoTryAgainError):
    """The shared 60-second request deadline expired before a validated
    proposal was produced."""


class SeoAllProvidersUnavailableError(SeoTryAgainError):
    """Every configured provider answered with a recognised
    provider-unavailable failure; there was no next provider left to try."""

    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons = tuple(reasons)
        detail = "; ".join(self.reasons) if self.reasons else "no provider was configured"
        super().__init__(f"no provider is available: {detail}")


class ProviderTimeoutError(SeoTryAgainError):
    """A provider's subprocess did not finish before the shared deadline
    expired -- distinct from :class:`SeoDeadlineExceededError`, which is the
    orchestrator refusing to start another call once time is already up."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(f"{provider}: timed out before the shared deadline")


class ProviderGenerationError(SeoTryAgainError):
    """A provider's CLI exited abnormally for a reason that
    :func:`classify_process_failure` does not recognise as availability."""

    def __init__(self, provider: str, returncode: int | None, detail: str) -> None:
        self.provider = provider
        self.returncode = returncode
        super().__init__(
            f"{provider}: exited {returncode} ({detail})"
            if detail
            else f"{provider}: exited {returncode}"
        )


_AVAILABILITY_MARKERS: tuple[str, ...] = (
    # authentication
    "not logged in",
    "not authenticated",
    "authentication failed",
    "unauthorized",
    "unauthenticated",
    "forbidden",
    "login required",
    "run `codex login`",
    "run 'codex login'",
    # quota / billing
    "quota",
    "insufficient_quota",
    "billing",
    "usage limit",
    "credit balance",
    # Claude Code's subscription-window sentences. They do not say "usage
    # limit" or "rate limit" -- "You've hit your weekly limit" is the one a
    # spent Claude subscription actually prints.
    "weekly limit",
    "session limit",
    "spend limit",
    "usage credits",
    "opus limit",
    "sonnet limit",
    # rate limiting
    "rate limit",
    "rate-limited",
    "rate_limit",
    "too many requests",
)
"""Substrings (matched case-insensitively) that a CLI's own stdout/stderr is
checked against. Deliberately conservative and stdlib-only: the classifier
never guesses at an internal error message it does not recognise, per the
settled plan -- an unrecognised failure is "Try again", not a silent
fallback to the next provider.

Deliberately excludes bare HTTP status numbers ("401", "403", "429") as
plain substrings: SEO copy is free-form generated prose that can legitimately
contain a three-digit number (a street address, a model number, a traceback
line number), and the settled plan is explicit that an unrecognised failure
must surface as "Try again", not be silently misread as availability because
a number happened to appear. :data:`_HTTP_STATUS_PATTERN` below still
recognises a status code when it is actually reported as one, and a
structured ``api_error_status`` on a CLI envelope is the other place a bare
status is trusted -- it is a field, not a number floating in prose."""

_HTTP_STATUS_PATTERN = re.compile(r"\bhttp\D{0,5}(401|403|429)\b", re.IGNORECASE)
_ERROR_PREFIX = re.compile(r"^error:\s*", re.IGNORECASE)
"""An explicit "HTTP 401"/"HTTP/1.1 403"/"http status 429"-shaped status
line. A bare status number in prose is not trusted; this pattern is, because
it is anchored to the word "http". A structured ``api_error_status`` is
trusted separately, in :func:`_api_status`."""

_AUTH_OR_LIMIT_STATUS = frozenset({401, 403, 429})
"""HTTP statuses that mean sign-in, permission, or a rate/usage limit when a
CLI reports them as ``api_error_status``. 500 and 529 stay "Try again": they
are the service failing, not this account being blocked."""

_MAX_DETAIL_CHARS = 500
"""How much of an unrecognised CLI dump may reach the editor. A Claude
``--output-format json`` envelope is several kilobytes of session id and
token counters; past this, the Listing Details failure chip grows to the
width of that one unbreakable string and paints over the brief."""


def classify_process_failure(
    provider: str, *, returncode: int | None, stdout: str, stderr: str
) -> ProviderUnavailableError | ProviderGenerationError:
    """Sort one nonzero-exit CLI invocation into the two failure categories
    the settled plan distinguishes: a recognised availability failure (falls
    through to the next provider), or anything else (surfaces as "Try
    again"). Never raises; the caller decides whether/when to raise the
    result.

    The text classified -- and the text the seller is shown -- is the CLI's
    own sentence, not its raw stdout. Claude's ``--output-format json``
    exits 1 with a result envelope whose ``result`` is that sentence
    ("You've hit your weekly limit · resets …") and whose other fields are
    telemetry. Codex prints a transcript (banner, session id, the echoed
    prompt) and then the failure as an ``ERROR:`` line; that line is the
    sentence, and a word in the prompt is not.
    """
    shown, status = _seller_text(stdout, stderr)
    shown = _clip(shown)
    if _is_unavailable(shown, status):
        return ProviderUnavailableError(provider, _as_sentence(shown))
    return ProviderGenerationError(provider, returncode, shown)


def _seller_text(stdout: str, stderr: str) -> tuple[str, int | None]:
    """The text a seller should read, and a structured HTTP status if that
    same stream carried one.

    stderr wins when it is prose: that is the CLI's own words, and a JSON
    envelope on the other stream must not hide them. When the stream we
    would have shown *is* an envelope (Claude's one JSON object, or Codex's
    JSONL), the sentence is ``result`` / ``message`` / ``error.message``
    and the rest -- session ids, token counters -- is dropped. A Codex
    transcript is the same kind of thing in prose: the ``ERROR:`` line is
    the sentence, and the banner and the echoed prompt are dropped. The
    prompt is allowed to say "quota"; that must not read as the account
    being out of quota.
    """
    err = stderr.strip()
    out = stdout.strip()
    primary = err or out
    if not primary:
        return "", None
    envelope = _envelope(primary)
    if envelope is not None:
        sentence = _sentence(envelope)
        status = _api_status(envelope)
        if sentence:
            return _as_sentence(sentence), status
        if status in _AUTH_OR_LIMIT_STATUS:
            return f"HTTP {status}", status
        return primary, status
    failure = _failure_lines(primary)
    if failure:
        return _as_sentence(failure), None
    return primary, None


def _failure_lines(text: str) -> str | None:
    """The ``ERROR:`` lines in a CLI transcript, in order, duplicates dropped.

    Codex exits 1 with the whole turn on stderr: a banner, the session id,
    the prompt it was given, then ``ERROR: You've hit your usage limit. …``
    twice. The line is the failure. Anything above it, including a prompt
    that happens to contain the word "quota", is not.
    """
    seen: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not _ERROR_PREFIX.match(line):
            continue
        body = _ERROR_PREFIX.sub("", line, count=1).strip()
        if body and body not in seen:
            seen.append(body)
    if not seen:
        return None
    return " ".join(seen)


def _envelope(text: str) -> dict[str, Any] | None:
    """One JSON object, or the last JSONL object that carries a sentence.

    Mixed prose is not an envelope: one log line beside a JSON object must
    stay the log line. A JSONL stream is an envelope only when every
    non-empty line is itself an object.
    """
    whole = _parse_object(text)
    if whole is not None:
        return whole
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    objects: list[dict[str, Any]] = []
    for line in lines:
        obj = _parse_object(line)
        if obj is None:
            return None
        objects.append(obj)
    for obj in reversed(objects):
        if _sentence(obj):
            return obj
    return objects[-1]


def _parse_object(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(value, dict):
        return value
    return None


def _sentence(envelope: dict[str, Any]) -> str | None:
    for key in ("result", "message"):
        found = _text(envelope.get(key))
        if found:
            return found
    error = envelope.get("error")
    found = _text(error)
    if found:
        return found
    if isinstance(error, dict):
        return _text(error.get("message"))
    return None


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    compact = " ".join(value.split())
    return compact or None


def _api_status(envelope: dict[str, Any]) -> int | None:
    raw = envelope.get("api_error_status")
    # bool is an int subclass; a JSON `true` must not read as status 1.
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw


def _is_unavailable(shown: str, status: int | None) -> bool:
    if status in _AUTH_OR_LIMIT_STATUS:
        return True
    folded = shown.casefold()
    if any(marker in folded for marker in _AVAILABILITY_MARKERS):
        return True
    return _HTTP_STATUS_PATTERN.search(shown) is not None


def _as_sentence(text: str) -> str:
    if text and text[-1] not in ".!?":
        return text + "."
    return text


def _clip(text: str) -> str:
    compact = " ".join(text.split())
    if len(compact) <= _MAX_DETAIL_CHARS:
        return compact
    return compact[: _MAX_DETAIL_CHARS - 1].rstrip() + "…"
