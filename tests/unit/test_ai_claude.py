"""``ai/claude.py``: the Claude Code CLI adapter behind `SeoProvider` (AI SEO
implementation plan, PR4, items 1-4).

Same doubling strategy as `test_ai_codex.py`: `subprocess.run` is replaced
for readiness checks, `run_managed` is replaced for generate/argv checks --
no real `claude` process runs in this suite.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from etsy_listings.ai import claude
from etsy_listings.ai.errors import (
    ProviderCancelledError,
    ProviderGenerationError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from etsy_listings.ai.models import (
    Deadline,
    GarmentContext,
    ProviderReadiness,
    RepairContext,
    SeoRequest,
)
from etsy_listings.ai.process import ProcessResult
from etsy_listings.ai.prompt import RESPONSE_SCHEMA

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


def _provider(tmp_path: Path, *, binary: str = "claude") -> claude.ClaudeProvider:
    prompt_file = tmp_path / "prompts" / "seo.md"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text("Write great SEO copy.", encoding="utf-8")
    return claude.ClaudeProvider(workspace_root=tmp_path, prompt_file=prompt_file, binary=binary)


# --------------------------------------------------------------- readiness


class _FakeRun:
    def __init__(self, table: dict[tuple[str, ...], subprocess.CompletedProcess[str]]) -> None:
        self.table = table
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        key = tuple(argv[1:3])
        if key not in self.table:
            raise AssertionError(f"unexpected subprocess.run call: {argv!r}")
        return self.table[key]


def _ok(stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


def test_readiness_fails_when_executable_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(claude.shutil, "which", lambda name: None)
    provider = _provider(tmp_path)

    readiness = provider.readiness()

    assert readiness == ProviderReadiness(ready=False, reason="claude was not found on PATH")


def test_readiness_fails_when_not_logged_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(claude.shutil, "which", lambda name: "/usr/bin/claude")
    fake = _FakeRun({("auth", "status"): _ok(stdout=json.dumps({"loggedIn": False}))})
    monkeypatch.setattr(claude.subprocess, "run", fake)
    provider = _provider(tmp_path)

    readiness = provider.readiness()

    assert readiness.ready is False
    assert "authenticated" in (readiness.reason or "")


def test_readiness_fails_when_auth_status_is_not_valid_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(claude.shutil, "which", lambda name: "/usr/bin/claude")
    fake = _FakeRun({("auth", "status"): _ok(stdout="not json")})
    monkeypatch.setattr(claude.subprocess, "run", fake)
    provider = _provider(tmp_path)

    readiness = provider.readiness()

    assert readiness.ready is False


def test_readiness_fails_when_auth_status_cannot_be_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(claude.shutil, "which", lambda name: "/usr/bin/claude")

    def _raise(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise OSError("boom")

    monkeypatch.setattr(claude.subprocess, "run", _raise)
    provider = _provider(tmp_path)

    readiness = provider.readiness()

    assert readiness.ready is False
    assert "boom" in (readiness.reason or "")


def test_readiness_fails_when_auth_status_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(claude.shutil, "which", lambda name: "/usr/bin/claude")
    fake = _FakeRun({("auth", "status"): subprocess.CompletedProcess([], 1, stdout="", stderr="")})
    monkeypatch.setattr(claude.subprocess, "run", fake)
    provider = _provider(tmp_path)

    readiness = provider.readiness()

    assert readiness.ready is False
    assert "auth status" in (readiness.reason or "")


def test_readiness_fails_when_help_check_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(claude.shutil, "which", lambda name: "/usr/bin/claude")

    def _run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if tuple(argv[1:3]) == ("auth", "status"):
            return _ok(stdout=_AUTH_STATUS_JSON)
        raise OSError("boom")

    monkeypatch.setattr(claude.subprocess, "run", _run)
    provider = _provider(tmp_path)

    readiness = provider.readiness()

    assert readiness.ready is False
    assert "boom" in (readiness.reason or "")


def test_readiness_fails_when_help_check_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(claude.shutil, "which", lambda name: "/usr/bin/claude")

    def _run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if tuple(argv[1:3]) == ("auth", "status"):
            return _ok(stdout=_AUTH_STATUS_JSON)
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="")

    monkeypatch.setattr(claude.subprocess, "run", _run)
    provider = _provider(tmp_path)

    readiness = provider.readiness()

    assert readiness.ready is False
    assert "-p --help" in (readiness.reason or "")


def test_readiness_fails_when_help_is_missing_required_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(claude.shutil, "which", lambda name: "/usr/bin/claude")
    fake = _FakeRun(
        {
            ("auth", "status"): _ok(stdout=_AUTH_STATUS_JSON),
            ("-p", "--help"): _ok(stdout="Usage: claude [options] [prompt]\n"),
        }
    )
    monkeypatch.setattr(claude.subprocess, "run", fake)
    provider = _provider(tmp_path)

    readiness = provider.readiness()

    assert readiness.ready is False
    assert "tools" in (readiness.reason or "").casefold()


def test_readiness_fails_when_prompt_file_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(claude.shutil, "which", lambda name: "/usr/bin/claude")
    fake = _FakeRun(
        {
            ("auth", "status"): _ok(stdout=_AUTH_STATUS_JSON),
            ("-p", "--help"): _ok(stdout=_HELP_TEXT),
        }
    )
    monkeypatch.setattr(claude.subprocess, "run", fake)
    prompt_file = tmp_path / "prompts" / "seo.md"
    provider = claude.ClaudeProvider(workspace_root=tmp_path, prompt_file=prompt_file)

    readiness = provider.readiness()

    assert readiness.ready is False
    assert "seo.md" in (readiness.reason or "")


def test_readiness_is_ready_when_every_check_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(claude.shutil, "which", lambda name: "/usr/bin/claude")
    fake = _FakeRun(
        {
            ("auth", "status"): _ok(stdout=_AUTH_STATUS_JSON),
            ("-p", "--help"): _ok(stdout=_HELP_TEXT),
        }
    )
    monkeypatch.setattr(claude.subprocess, "run", fake)
    provider = _provider(tmp_path)

    assert provider.readiness() == ProviderReadiness(ready=True)


# ------------------------------------------------------------------ generate


def _completed(payload: dict[str, Any]) -> str:
    return json.dumps(payload)


def _patch_run_managed(
    monkeypatch: pytest.MonkeyPatch, result: ProcessResult
) -> list[dict[str, Any]]:
    # See `CodexProvider._resolved_binary`'s docstring / this project's
    # test_ai_codex.py: `generate()` resolves the binary through
    # `shutil.which` rather than trusting the bare name is launchable, so
    # this needs patching deterministically too, independent of whatever
    # happens to be on the machine actually running this test suite.
    monkeypatch.setattr(claude.shutil, "which", lambda name: f"/resolved/{name}")
    calls: list[dict[str, Any]] = []

    def fake_run_managed(argv: list[str], **kwargs: Any) -> ProcessResult:
        calls.append({"argv": list(argv), **kwargs})
        return result

    monkeypatch.setattr(claude, "run_managed", fake_run_managed)
    return calls


def test_generate_builds_the_expected_argv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    envelope = _completed(
        {"type": "result", "subtype": "success", "is_error": False, "result": '{"ok": true}'}
    )
    calls = _patch_run_managed(
        monkeypatch,
        ProcessResult(returncode=0, stdout=envelope, stderr="", timed_out=False, cancelled=False),
    )
    provider = _provider(tmp_path)
    request = _request(tmp_path)
    deadline = Deadline.starting_now(seconds=60)

    result = provider.generate(request, deadline)

    assert result.provider == "claude"
    assert result.raw_output == '{"ok": true}'
    assert len(calls) == 1
    call = calls[0]
    argv = call["argv"]
    assert argv[0] == "/resolved/claude"  # the shutil.which-resolved path, not the bare name
    assert "-p" in argv
    assert "--output-format" in argv and argv[argv.index("--output-format") + 1] == "json"
    assert "--no-session-persistence" in argv
    assert "--tools" in argv
    assert "--json-schema" in argv
    schema_arg = argv[argv.index("--json-schema") + 1]
    assert json.loads(schema_arg) == RESPONSE_SCHEMA
    assert call["cwd"] == tmp_path
    assert call["deadline"] is deadline
    # The prompt is piped via stdin (see `ai/codex.py`'s own reasoning, which
    # applies here too, only more so since Claude's prompt also echoes the
    # response schema): it must never appear as a trailing argv element,
    # which is what would risk a platform argv-length limit.
    assert argv[-1] == json.dumps(RESPONSE_SCHEMA)
    assert not any(str(request.design_image) in arg for arg in argv)


def test_generate_sends_the_seller_prompt_and_context_over_stdin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    envelope = _completed({"type": "result", "is_error": False, "result": "{}"})
    calls = _patch_run_managed(
        monkeypatch,
        ProcessResult(returncode=0, stdout=envelope, stderr="", timed_out=False, cancelled=False),
    )
    provider = _provider(tmp_path)
    request = _request(tmp_path)

    provider.generate(request, Deadline.starting_now(seconds=60))

    stdin_text = calls[0]["input_text"]
    assert "Write great SEO copy." in stdin_text
    assert request.brief in stdin_text
    assert str(request.design_image) in stdin_text


def test_generate_appends_the_repair_block_when_repairing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    envelope = _completed({"type": "result", "is_error": False, "result": "{}"})
    calls = _patch_run_managed(
        monkeypatch,
        ProcessResult(returncode=0, stdout=envelope, stderr="", timed_out=False, cancelled=False),
    )
    provider = _provider(tmp_path)
    request = _request(tmp_path)
    repair = RepairContext(
        prior_raw_output='{"titles": []}', reasons=("titles: expected exactly 3",)
    )

    provider.generate(request, Deadline.starting_now(seconds=60), repair=repair)

    stdin_text = calls[0]["input_text"]
    assert '{"titles": []}' in stdin_text
    assert "titles: expected exactly 3" in stdin_text


def test_generate_raises_cancelled_when_the_process_was_cancelled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_run_managed(
        monkeypatch,
        ProcessResult(returncode=None, stdout="", stderr="", timed_out=False, cancelled=True),
    )
    provider = _provider(tmp_path)

    with pytest.raises(ProviderCancelledError):
        provider.generate(_request(tmp_path), Deadline.starting_now(seconds=60))


def test_generate_raises_timeout_when_the_process_timed_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_run_managed(
        monkeypatch,
        ProcessResult(returncode=None, stdout="", stderr="", timed_out=True, cancelled=False),
    )
    provider = _provider(tmp_path)

    with pytest.raises(ProviderTimeoutError):
        provider.generate(_request(tmp_path), Deadline.starting_now(seconds=60))


def test_generate_classifies_an_availability_failure_from_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_run_managed(
        monkeypatch,
        ProcessResult(
            returncode=1,
            stdout="",
            stderr="Error: not authenticated",
            timed_out=False,
            cancelled=False,
        ),
    )
    provider = _provider(tmp_path)

    with pytest.raises(ProviderUnavailableError):
        provider.generate(_request(tmp_path), Deadline.starting_now(seconds=60))


def test_generate_classifies_an_unrecognised_failure_as_generation_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_run_managed(
        monkeypatch,
        ProcessResult(returncode=1, stdout="", stderr="boom", timed_out=False, cancelled=False),
    )
    provider = _provider(tmp_path)

    with pytest.raises(ProviderGenerationError):
        provider.generate(_request(tmp_path), Deadline.starting_now(seconds=60))


def test_generate_treats_is_error_envelope_as_generation_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    envelope = _completed({"type": "result", "is_error": True, "result": "overloaded"})
    _patch_run_managed(
        monkeypatch,
        ProcessResult(returncode=0, stdout=envelope, stderr="", timed_out=False, cancelled=False),
    )
    provider = _provider(tmp_path)

    with pytest.raises(ProviderGenerationError):
        provider.generate(_request(tmp_path), Deadline.starting_now(seconds=60))


def test_generate_classifies_an_is_error_envelope_reporting_auth_failure_as_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # `claude -p --output-format json` reports an auth/quota/rate-limit
    # failure inside its `is_error: true` envelope, with exit code 0 -- the
    # same recognised-availability text an exit-code failure would carry,
    # just delivered through the envelope instead of stderr. It must be
    # classified the same way (`classify_process_failure`), not read as a
    # generic generation error.
    envelope = _completed(
        {"type": "result", "is_error": True, "result": "Error: not authenticated"}
    )
    _patch_run_managed(
        monkeypatch,
        ProcessResult(returncode=0, stdout=envelope, stderr="", timed_out=False, cancelled=False),
    )
    provider = _provider(tmp_path)

    with pytest.raises(ProviderUnavailableError):
        provider.generate(_request(tmp_path), Deadline.starting_now(seconds=60))


def test_generate_treats_unparseable_envelope_as_generation_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_run_managed(
        monkeypatch,
        ProcessResult(
            returncode=0, stdout="not json at all", stderr="", timed_out=False, cancelled=False
        ),
    )
    provider = _provider(tmp_path)

    with pytest.raises(ProviderGenerationError):
        provider.generate(_request(tmp_path), Deadline.starting_now(seconds=60))
