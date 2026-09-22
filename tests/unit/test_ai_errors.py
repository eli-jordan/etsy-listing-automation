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
