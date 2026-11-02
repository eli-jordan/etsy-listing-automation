"""``ai/claude.py``: the Claude Code CLI adapter behind `AiProvider` (AI SEO
implementation plan, PR4, items 1-4).

Same doubling strategy as `test_ai_codex.py`: every provider runs on a
`ScriptedCliHost` that answers the readiness probes and the managed
generate call -- no real `claude` process runs in this suite.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from etsy_listings.core.ai import claude
from etsy_listings.core.ai.errors import (
    ProviderCancelledError,
    ProviderGenerationError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from etsy_listings.core.ai.models import (
    Deadline,
    GarmentContext,
    ProviderReadiness,
    ProviderTask,
    RepairContext,
    SeoRequest,
)
from etsy_listings.core.ai.orchestrator import run_task
from etsy_listings.core.ai.process import ProcessResult
from etsy_listings.core.ai.prompt import RESPONSE_SCHEMA, build_seo_task
from etsy_listings.core.ai.providers import FakeAiProvider

from tests.support.cli_host import (
    RunAnswer,
    ScriptedCliHost,
    completed,
    finished,
    never_launched,
)

_HELP_TEXT = """
Options:
  --json-schema <schema>                JSON Schema for structured output
  --no-session-persistence              Disable session persistence
  --output-format <format>              Output format (only works with --print)
  --permission-mode <mode>              Permission mode to use for the session
  --permission-prompts <target>         Who answers permission prompts with --print
  --tools <tools...>                    Specify the list of available tools
"""

_AUTH_STATUS_JSON = json.dumps({"loggedIn": True})


def _generating(result: ProcessResult) -> ScriptedCliHost:
    """`claude` on PATH, every managed run answering ``result``. `generate()`
    resolves the binary through `which` rather than trusting the bare name is
    launchable (see `LocalCliProvider._resolved_binary`)."""
    return ScriptedCliHost(installed={"claude": "/resolved/claude"}, managed={(): result})


@pytest.mark.parametrize(
    "stream",
    [
        "stdout",
        "stderr",
        "error-envelope",
        "structured-error",
        "structured-code",
        "effort-envelope",
    ],
)
def test_rejected_saved_claude_model_falls_back_through_the_process_contract(
    tmp_path: Path, stream: str
) -> None:
    # Observed vendor wording, Anthropic claude-code issue #103174, recorded
    # in the Admin audit. No installed CLI or live generation is needed.
    sentence = "There's an issue with the selected model (retired-model). It may not exist."
    stdout, stderr, code = "", "", 1
    if stream == "stdout":
        stdout = sentence
    elif stream == "stderr":
        stderr = sentence
    elif stream == "error-envelope":
        stdout, code = json.dumps({"type": "result", "is_error": True, "result": sentence}), 0
    elif stream == "structured-error":
        stdout, code = (
            json.dumps({"type": "result", "is_error": True, "error": {"type": "model_not_found"}}),
            0,
        )
    elif stream == "structured-code":
        stdout, code = (
            json.dumps(
                {
                    "type": "result",
                    "is_error": True,
                    "error": {
                        "code": "model_not_found",
                        "message": "The selected model cannot be used.",
                    },
                }
            ),
            0,
        )
    else:
        stdout, code = (
            json.dumps(
                {
                    "type": "result",
                    "is_error": True,
                    "result": "error: invalid value 'extreme' for '--effort <LEVEL>'",
                }
            ),
            0,
        )
    host = _generating(ProcessResult(code, stdout, stderr, False, False))
    effort = "extreme" if stream == "effort-envelope" else None
    provider = claude.ClaudeProvider(tmp_path, model="retired-model", effort=effort, host=host)
    fallback = FakeAiProvider("grok", responses=["valid"])

    result = run_task(
        ProviderTask("test", {}, tmp_path / "unused.png"), lambda raw: raw, [provider, fallback]
    )

    assert result == "valid"
    assert len(fallback.tasks) == 1
    assert provider.model == "retired-model"
    assert provider.effort == effort


@pytest.mark.parametrize(
    "envelope",
    [
        {"is_error": True, "result": "The generated model output may not exist on disk."},
        {
            "is_error": True,
            "result": "There's an issue with the selected model output: malformed JSON.",
        },
        {"is_error": True, "result": "The response mentioned model_not_found."},
        {"is_error": True, "result": "generation failed", "telemetry": {"code": "model_not_found"}},
        {"is_error": True, "error": {"type": "generation_error", "message": "generation failed"}},
    ],
)
def test_generation_failures_do_not_fall_back_for_an_incidental_model_mention(
    tmp_path: Path, envelope: dict[str, Any]
) -> None:
    host = _generating(finished(json.dumps(envelope)))
    fallback = FakeAiProvider("grok", responses=["valid"])
    with pytest.raises(ProviderGenerationError):
        run_task(
            ProviderTask("test", {}, tmp_path / "unused.png"),
            lambda raw: raw,
            [claude.ClaudeProvider(tmp_path, host=host), fallback],
        )
    assert fallback.tasks == []


def _request(tmp_path: Path) -> SeoRequest:
    design = tmp_path / "designs" / "front.png"
    design.parent.mkdir(parents=True, exist_ok=True)
    design.write_bytes(b"\x89PNG")
    return SeoRequest(
        brief="A retro sunset tee.",
        product_type="t-shirt",
        etsy_category="Clothing",
        materials=("Comfort Colors 1717",),
        colors=("navy",),
        garment=GarmentContext(brand="Comfort Colors", model="1717"),
        design_image=design,
    )


def _provider(tmp_path: Path, host: ScriptedCliHost) -> claude.ClaudeProvider:
    return claude.ClaudeProvider(workspace_root=tmp_path, host=host)


def _task(tmp_path: Path) -> ProviderTask:
    """An ordinary SEO task, assembled the way `server/api/seo.py` assembles one
    -- see `test_ai_codex.py._task` for why the seller prose is a plain
    string here and not a file."""
    return build_seo_task("Write great SEO copy.", _request(tmp_path))


# --------------------------------------------------------------- readiness


def _installed(runs: dict[tuple[str, ...], RunAnswer]) -> ScriptedCliHost:
    """`claude` on PATH, its probes answering from ``runs``."""
    return ScriptedCliHost(installed={"claude": "/usr/bin/claude"}, runs=runs)


def test_readiness_fails_when_executable_is_missing(tmp_path: Path) -> None:
    readiness = _provider(tmp_path, ScriptedCliHost()).readiness()

    assert readiness == ProviderReadiness(ready=False, reason="claude was not found on PATH")


def test_readiness_fails_when_not_logged_in(tmp_path: Path) -> None:
    host = _installed({("auth", "status"): completed(json.dumps({"loggedIn": False}))})

    readiness = _provider(tmp_path, host).readiness()

    assert readiness.ready is False
    assert "authenticated" in (readiness.reason or "")


def test_readiness_fails_when_auth_status_is_not_valid_json(tmp_path: Path) -> None:
    host = _installed({("auth", "status"): completed("not json")})

    readiness = _provider(tmp_path, host).readiness()

    assert readiness.ready is False


def test_readiness_fails_when_auth_status_cannot_be_run(tmp_path: Path) -> None:
    host = _installed({("auth", "status"): OSError("boom")})

    readiness = _provider(tmp_path, host).readiness()

    assert readiness.ready is False
    assert "boom" in (readiness.reason or "")


def test_readiness_fails_when_auth_status_exits_nonzero(tmp_path: Path) -> None:
    host = _installed({("auth", "status"): completed(returncode=1)})

    readiness = _provider(tmp_path, host).readiness()

    assert readiness.ready is False
    assert "auth status" in (readiness.reason or "")


def test_readiness_fails_when_help_check_raises(tmp_path: Path) -> None:
    host = _installed(
        {("auth", "status"): completed(_AUTH_STATUS_JSON), ("-p", "--help"): OSError("boom")}
    )

    readiness = _provider(tmp_path, host).readiness()

    assert readiness.ready is False
    assert "boom" in (readiness.reason or "")


def test_readiness_fails_when_help_check_exits_nonzero(tmp_path: Path) -> None:
    host = _installed(
        {
            ("auth", "status"): completed(_AUTH_STATUS_JSON),
            ("-p", "--help"): completed(returncode=1),
        }
    )

    readiness = _provider(tmp_path, host).readiness()

    assert readiness.ready is False
    assert "-p --help" in (readiness.reason or "")


def test_readiness_fails_when_help_is_missing_required_flags(tmp_path: Path) -> None:
    host = _installed(
        {
            ("auth", "status"): completed(_AUTH_STATUS_JSON),
            ("-p", "--help"): completed("Usage: claude [options] [prompt]\n"),
        }
    )

    readiness = _provider(tmp_path, host).readiness()

    assert readiness.ready is False
    assert "tools" in (readiness.reason or "").casefold()


def test_readiness_says_nothing_about_a_prompt_file(tmp_path: Path) -> None:
    """The same rule `test_ai_codex.py` states: a prompt file's existence is
    a fact about a request, not about this CLI."""
    host = _installed(
        {
            ("auth", "status"): completed(_AUTH_STATUS_JSON),
            ("-p", "--help"): completed(_HELP_TEXT),
        }
    )

    readiness = claude.ClaudeProvider(workspace_root=tmp_path, host=host).readiness()

    assert readiness == ProviderReadiness(ready=True)


def test_readiness_is_ready_when_every_check_passes(tmp_path: Path) -> None:
    host = _installed(
        {
            ("auth", "status"): completed(_AUTH_STATUS_JSON),
            ("-p", "--help"): completed(_HELP_TEXT),
        }
    )

    assert _provider(tmp_path, host).readiness() == ProviderReadiness(ready=True)
    assert host.ran == [
        ["/usr/bin/claude", "auth", "status"],
        ["/usr/bin/claude", "-p", "--help"],
    ]


# ------------------------------------------------------------------ generate


def _completed(payload: dict[str, Any]) -> str:
    return json.dumps(payload)


def test_generate_builds_the_expected_argv(tmp_path: Path) -> None:
    envelope = _completed(
        {"type": "result", "subtype": "success", "is_error": False, "result": '{"ok": true}'}
    )
    host = _generating(finished(envelope))
    request = _request(tmp_path)
    deadline = Deadline.starting_now(seconds=60)

    result = _provider(tmp_path, host).generate(_task(tmp_path), deadline)

    assert result.provider == "claude"
    assert result.raw_output == '{"ok": true}'
    assert len(host.managed_calls) == 1
    call = host.last_managed
    argv = call.argv
    assert argv[0] == "/resolved/claude"  # the which-resolved path, not the bare name
    assert "-p" in argv
    assert "--output-format" in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert "--no-session-persistence" in argv
    assert "--tools" in argv
    assert "--json-schema" in argv
    schema_arg = argv[argv.index("--json-schema") + 1]
    assert json.loads(schema_arg) == RESPONSE_SCHEMA
    assert call.cwd == tmp_path
    assert call.deadline is deadline
    # The prompt is piped via stdin (see `ai/codex.py`'s own reasoning, which
    # applies here too, only more so since Claude's prompt also echoes the
    # response schema): it must never appear as a trailing argv element,
    # which is what would risk a platform argv-length limit.
    assert argv[-1] == json.dumps(RESPONSE_SCHEMA)
    assert not any(str(request.design_image) in arg for arg in argv)


def test_generate_sends_the_seller_prompt_and_context_over_stdin(tmp_path: Path) -> None:
    host = _generating(finished(_completed({"type": "result", "is_error": False, "result": "{}"})))
    request = _request(tmp_path)

    _provider(tmp_path, host).generate(_task(tmp_path), Deadline.starting_now(seconds=60))

    stdin_text = host.last_managed.input_text
    assert "Write great SEO copy." in stdin_text
    assert request.brief in stdin_text
    assert str(request.design_image) in stdin_text


def test_generate_appends_the_repair_block_when_repairing(tmp_path: Path) -> None:
    host = _generating(finished(_completed({"type": "result", "is_error": False, "result": "{}"})))
    repair = RepairContext(
        prior_raw_output='{"titles": []}', reasons=("titles: expected exactly 3",)
    )

    _provider(tmp_path, host).generate(
        _task(tmp_path), Deadline.starting_now(seconds=60), repair=repair
    )

    stdin_text = host.last_managed.input_text
    assert '{"titles": []}' in stdin_text
    assert "titles: expected exactly 3" in stdin_text


@pytest.mark.parametrize(
    ("result", "error"),
    [
        (ProcessResult(None, "", "", timed_out=False, cancelled=True), ProviderCancelledError),
        (ProcessResult(None, "", "", timed_out=True, cancelled=False), ProviderTimeoutError),
        # An availability failure from the exit code, recognised by its text.
        (finished(stderr="Error: not authenticated", returncode=1), ProviderUnavailableError),
        (finished(stderr="boom", returncode=1), ProviderGenerationError),
        (finished("not json at all"), ProviderGenerationError),
        (
            finished(_completed({"type": "result", "is_error": True, "result": "overloaded"})),
            ProviderGenerationError,
        ),
        # `claude -p --output-format json` reports an auth/quota/rate-limit
        # failure inside its `is_error: true` envelope, with exit code 0 --
        # the same recognised-availability text an exit-code failure would
        # carry. It is classified the same way (`classify_process_failure`),
        # not read as a generic generation error.
        (
            finished(
                _completed(
                    {"type": "result", "is_error": True, "result": "Error: not authenticated"}
                )
            ),
            ProviderUnavailableError,
        ),
    ],
    ids=[
        "cancelled",
        "timed-out",
        "unavailable-exit",
        "unrecognised-exit",
        "unparseable-envelope",
        "is-error-envelope",
        "unavailable-envelope",
    ],
)
def test_generate_classifies_how_the_process_ended(
    tmp_path: Path, result: ProcessResult, error: type[Exception]
) -> None:
    with pytest.raises(error):
        _provider(tmp_path, _generating(result)).generate(
            _task(tmp_path), Deadline.starting_now(seconds=60)
        )


def test_generate_reports_a_weekly_limit_envelope_without_its_telemetry(tmp_path: Path) -> None:
    # `claude -p --output-format json` exits 1 on a subscription limit and
    # prints one envelope: the seller-facing sentence is `result`, and the
    # rest (session id, token counters) must not reach the editor.
    envelope = json.dumps(
        {
            "type": "result",
            "is_error": True,
            "api_error_status": 429,
            "session_id": "23b260fd-9790-4e62-8e60-818834fa4acb",
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "result": "You've hit your weekly limit · resets Sep 29, 7am (Europe/Oslo)",
        }
    )
    host = _generating(finished(envelope, returncode=1))

    with pytest.raises(ProviderUnavailableError) as excinfo:
        _provider(tmp_path, host).generate(_task(tmp_path), Deadline.starting_now(seconds=60))

    message = str(excinfo.value)
    assert message == "claude: You've hit your weekly limit · resets Sep 29, 7am (Europe/Oslo)."
    assert "session_id" not in message
    assert "input_tokens" not in message


def test_generate_names_a_bare_is_error_envelope(tmp_path: Path) -> None:
    host = _generating(finished(_completed({"type": "result", "is_error": True})))

    with pytest.raises(ProviderGenerationError, match="claude reported is_error"):
        _provider(tmp_path, host).generate(_task(tmp_path), Deadline.starting_now(seconds=60))


def test_generate_with_no_binary_on_path_is_unavailable_so_the_next_provider_runs(
    tmp_path: Path,
) -> None:
    # A machine with only one of the two CLIs installed. Launching the bare
    # name fails with WinError 2, which is not an availability failure the
    # orchestrator falls through on -- it used to end the whole run.
    host = ScriptedCliHost(managed={(): never_launched})

    with pytest.raises(ProviderUnavailableError, match="claude was not found on PATH"):
        _provider(tmp_path, host).generate(_task(tmp_path), Deadline.starting_now(seconds=60))
