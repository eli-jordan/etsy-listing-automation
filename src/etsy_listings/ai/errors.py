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

from collections.abc import Sequence


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
    "please run",
    "login required",
    "run `codex login`",
    "run 'codex login'",
    "401",
    "403",
    # quota / billing
    "quota",
    "insufficient_quota",
    "billing",
    "usage limit",
    "credit balance",
    # rate limiting
    "rate limit",
    "rate-limited",
    "rate_limit",
    "too many requests",
    "429",
)
"""Substrings (matched case-insensitively) that a CLI's own stdout/stderr is
checked against. Deliberately conservative and stdlib-only: the classifier
never guesses at an internal error message it does not recognise, per the
settled plan -- an unrecognised failure is "Try again", not a silent
fallback to the next provider."""


def classify_process_failure(
    provider: str, *, returncode: int | None, stdout: str, stderr: str
) -> ProviderUnavailableError | ProviderGenerationError:
    """Sort one nonzero-exit CLI invocation into the two failure categories
    the settled plan distinguishes: a recognised availability failure (falls
    through to the next provider), or anything else (surfaces as "Try
    again"). Never raises; the caller decides whether/when to raise the
    result.
    """
    combined = f"{stdout}\n{stderr}".casefold()
    for marker in _AVAILABILITY_MARKERS:
        if marker in combined:
            return ProviderUnavailableError(
                provider, reason=stderr.strip() or stdout.strip() or marker
            )
    detail = stderr.strip() or stdout.strip()
    return ProviderGenerationError(provider, returncode, detail)
