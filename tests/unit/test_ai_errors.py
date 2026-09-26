"""``ai/errors.py``: the exception hierarchy `ai/orchestrator.py` and both
CLI adapters share, and :func:`classify_process_failure`, the one place a
nonzero-exit CLI process is sorted into "provider unavailable" (fall through
to the next provider) versus everything else ("Try again", implementation
plan: "Only recognised provider-unavailable, authentication-quota, or
rate-limit failures fall through to Claude. Other failures show Try again")."""

from __future__ import annotations

import json

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


_WEEKLY_LIMIT = "You've hit your weekly limit · resets Sep 29, 7am (Europe/Oslo)"


def _claude_weekly_limit_envelope() -> str:
    """The compact `--output-format json` envelope Claude Code prints when a
    subscription window is spent. Exit code 1, `api_error_status` 429, and
    the sentence a seller can read in `result`; everything else is telemetry."""
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "api_error_status": 429,
            "terminal_reason": "api_error",
            "duration_api_ms": 0,
            "session_id": "23b260fd-9790-4e62-8e60-818834fa4acb",
            "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0},
            "modelUsage": {},
            "result": _WEEKLY_LIMIT,
        },
        separators=(",", ":"),
    )


def test_a_weekly_limit_sentence_without_a_status_code_is_unavailable() -> None:
    """Exit 0 delivers the sentence alone (`claude.py` pulls `result` out
    before classifying). It still has to fall through: the words are the
    subscription limit, and there is no `api_error_status` left to consult."""
    error = classify_process_failure("claude", returncode=0, stdout=_WEEKLY_LIMIT, stderr="")
    assert isinstance(error, ProviderUnavailableError)
    assert str(error) == f"claude: {_WEEKLY_LIMIT}."


def test_claude_weekly_limit_envelope_is_a_short_unavailable_error() -> None:
    error = classify_process_failure(
        "claude", returncode=1, stdout=_claude_weekly_limit_envelope(), stderr=""
    )
    assert isinstance(error, ProviderUnavailableError)
    assert str(error) == f"claude: {_WEEKLY_LIMIT}."
    assert "session_id" not in str(error)
    assert "input_tokens" not in str(error)
    assert "duration_api_ms" not in str(error)


def test_an_unrecognised_claude_envelope_keeps_its_sentence_and_drops_telemetry() -> None:
    stdout = json.dumps(
        {
            "type": "result",
            "is_error": True,
            "session_id": "23b260fd-9790-4e62-8e60-818834fa4acb",
            "usage": {"input_tokens": 12},
            "result": "the model stopped before producing JSON",
        },
        separators=(",", ":"),
    )
    error = classify_process_failure("claude", returncode=1, stdout=stdout, stderr="")
    assert isinstance(error, ProviderGenerationError)
    assert str(error) == "claude: exited 1 (the model stopped before producing JSON.)"
    assert "session_id" not in str(error)
    assert "input_tokens" not in str(error)


def test_api_error_status_429_is_unavailable_even_without_a_limit_phrase() -> None:
    stdout = json.dumps(
        {"type": "result", "is_error": True, "api_error_status": 429, "result": "Request rejected"}
    )
    error = classify_process_failure("claude", returncode=1, stdout=stdout, stderr="")
    assert isinstance(error, ProviderUnavailableError)
    assert str(error) == "claude: Request rejected."
    assert "api_error_status" not in str(error)


def test_a_number_inside_an_error_envelope_is_still_not_a_rate_limit() -> None:
    stdout = json.dumps(
        {
            "type": "result",
            "is_error": True,
            "result": "expected 3 titles, got 429",
            "session_id": "abc",
        }
    )
    error = classify_process_failure("claude", returncode=1, stdout=stdout, stderr="")
    assert isinstance(error, ProviderGenerationError)
    assert "expected 3 titles, got 429" in str(error)
    assert "session_id" not in str(error)


def test_stderr_prose_wins_over_a_json_envelope_on_stdout() -> None:
    stdout = json.dumps({"result": _WEEKLY_LIMIT, "session_id": "abc"})
    error = classify_process_failure(
        "claude", returncode=1, stdout=stdout, stderr="panic: index out of range"
    )
    assert isinstance(error, ProviderGenerationError)
    assert "panic: index out of range" in str(error)
    assert "weekly limit" not in str(error)


def test_codex_transcript_usage_limit_is_the_error_line_not_the_banner() -> None:
    """Codex 0.157 exits 1 with the turn on stderr. The limit is the
    ``ERROR:`` line at the bottom; the banner, session id and echoed prompt
    are not, even when the prompt itself says "quota"."""
    limit = (
        "You\u2019ve hit your usage limit. Upgrade to Pro "
        "(https://chatgpt.com/explore/pro), or try again at Sep 26th, 2026 1:10 AM."
    )
    stderr = (
        "OpenAI Codex v0.157.0\n"
        "--------\n"
        "workdir: C:\\Users\\Admin\\Desktop\\try-workspace\n"
        "model: gpt-5.6-terra\n"
        "session id: 01a0da7e-37ed-7880-9aab-4d19d93aead7\n"
        "--------\n"
        "user\n"
        "Do not meet a quota by inventing weak phrases.\n"
        "\n"
        f"ERROR: {limit}\n"
        f"ERROR: {limit}\n"
    )
    error = classify_process_failure("codex", returncode=1, stdout="", stderr=stderr)
    assert isinstance(error, ProviderUnavailableError)
    assert str(error) == f"codex: {limit}"
    assert "session id" not in str(error)
    assert "workdir" not in str(error)
    assert "inventing" not in str(error)


def test_codex_jsonl_usage_limit_is_the_error_sentence() -> None:
    message = "You've hit your usage limit. Try again at Sep 29, 7am."
    stderr = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-secret"}),
            json.dumps({"type": "error", "message": message}),
            json.dumps({"type": "turn.failed", "error": {"message": message}}),
        ]
    )
    error = classify_process_failure("codex", returncode=1, stdout="", stderr=stderr)
    assert isinstance(error, ProviderUnavailableError)
    assert str(error) == f"codex: {message}"
    assert "thread-secret" not in str(error)
    assert "thread.started" not in str(error)


def test_a_boolean_api_error_status_is_not_an_http_status() -> None:
    stdout = json.dumps({"is_error": True, "api_error_status": True, "result": "nope"})
    error = classify_process_failure("claude", returncode=1, stdout=stdout, stderr="")
    assert isinstance(error, ProviderGenerationError)
    assert str(error) == "claude: exited 1 (nope.)"


def test_api_error_status_without_a_sentence_is_named_as_http() -> None:
    stdout = json.dumps({"is_error": True, "api_error_status": 429, "session_id": "abc"})
    error = classify_process_failure("claude", returncode=1, stdout=stdout, stderr="")
    assert isinstance(error, ProviderUnavailableError)
    assert str(error) == "claude: HTTP 429."
    assert "session_id" not in str(error)


def test_empty_output_stays_a_generation_error() -> None:
    error = classify_process_failure("codex", returncode=1, stdout="  ", stderr="")
    assert isinstance(error, ProviderGenerationError)
    assert str(error) == "codex: exited 1"


def test_a_log_line_beside_json_is_not_parsed_as_an_envelope() -> None:
    stderr = 'panic: index out of range\n{"result": "stopped"}'
    error = classify_process_failure("claude", returncode=1, stdout="", stderr=stderr)
    assert isinstance(error, ProviderGenerationError)
    assert "panic: index out of range" in str(error)


def test_an_unrecognised_dump_is_shortened_so_it_cannot_flood_the_editor() -> None:
    error = classify_process_failure("claude", returncode=1, stdout="x" * 5000, stderr="")
    assert isinstance(error, ProviderGenerationError)
    text = str(error)
    assert len(text) < 600
    assert text.endswith("…)")
    assert "x" * 600 not in text
