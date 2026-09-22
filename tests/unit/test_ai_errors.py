"""``ai/errors.py``: the exception hierarchy `ai/orchestrator.py` and both
CLI adapters share, and :func:`classify_process_failure`, the one place a
nonzero-exit CLI process is sorted into "provider unavailable" (fall through
to the next provider) versus everything else ("Try again", implementation
plan: "Only recognised provider-unavailable, authentication-quota, or
rate-limit failures fall through to Claude. Other failures show Try again")."""

from __future__ import annotations

from etsy_listings.ai.errors import (
    ProviderGenerationError,
    ProviderUnavailableError,
    SeoTryAgainError,
    classify_process_failure,
)


def test_login_required_stderr_is_classified_as_unavailable() -> None:
    error = classify_process_failure(
        "codex", returncode=1, stdout="", stderr="Error: not logged in. Run `codex login`."
    )
    assert isinstance(error, ProviderUnavailableError)
    assert error.provider == "codex"


def test_rate_limit_stdout_is_classified_as_unavailable() -> None:
    error = classify_process_failure(
        "claude", returncode=1, stdout="429 Too Many Requests: rate limit exceeded", stderr=""
    )
    assert isinstance(error, ProviderUnavailableError)


def test_quota_message_is_classified_as_unavailable() -> None:
    error = classify_process_failure(
        "codex", returncode=1, stdout="", stderr="insufficient_quota: you have exceeded your quota"
    )
    assert isinstance(error, ProviderUnavailableError)


def test_unrecognised_failure_is_classified_as_generation_error() -> None:
    error = classify_process_failure(
        "codex", returncode=1, stdout="", stderr="panic: index out of range"
    )
    assert isinstance(error, ProviderGenerationError)
    assert not isinstance(error, ProviderUnavailableError)


def test_provider_generation_error_is_a_try_again_error() -> None:
    assert issubclass(ProviderGenerationError, SeoTryAgainError)


def test_classification_is_case_insensitive() -> None:
    error = classify_process_failure("codex", returncode=1, stdout="", stderr="NOT AUTHENTICATED")
    assert isinstance(error, ProviderUnavailableError)


def test_a_coincidental_number_in_generated_output_is_not_misclassified() -> None:
    """A bare "401"/"403"/"429" must never, by itself, read as an
    availability failure -- SEO copy is free-form generated prose that can
    legitimately contain a street address, model number, or traceback line
    number, and a real generation failure containing one must still surface
    as "Try again", not silently fall through to the next provider."""
    error = classify_process_failure(
        "codex",
        returncode=1,
        stdout="",
        stderr="AssertionError: expected 3 titles, got 429 at line 401 of generator.py (code 403)",
    )
    assert isinstance(error, ProviderGenerationError)
    assert not isinstance(error, ProviderUnavailableError)


def test_explicit_http_status_line_is_still_classified_as_unavailable() -> None:
    # Deliberately avoids every textual marker (no "unauthorized", "quota",
    # etc.) so this only passes if `_HTTP_STATUS_PATTERN` itself -- not one
    # of the substring markers -- is what recognises the status code.
    error = classify_process_failure(
        "claude", returncode=1, stdout="", stderr="network error: HTTP 401 received from server"
    )
    assert isinstance(error, ProviderUnavailableError)


def test_forbidden_is_classified_as_unavailable() -> None:
    error = classify_process_failure(
        "codex", returncode=1, stdout="", stderr="Error: 403 Forbidden: access denied"
    )
    assert isinstance(error, ProviderUnavailableError)


def test_generic_please_run_suggestion_is_not_misclassified_as_unavailable() -> None:
    """ "please run ..." is too generic a phrase to mean "you must log in" --
    an ordinary CLI error suggesting a next step (e.g. "please run with
    --verbose") must not be read as an availability failure."""
    error = classify_process_failure(
        "codex",
        returncode=1,
        stdout="",
        stderr="internal error: please run the command again with --verbose for details",
    )
    assert isinstance(error, ProviderGenerationError)
    assert not isinstance(error, ProviderUnavailableError)
