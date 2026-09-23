"""``ai/codex.py``: the Codex CLI adapter behind `AiProvider` (AI SEO
implementation plan, PR4, items 1-4).

Nothing here launches a real `codex` process. Readiness tests replace
`etsy_listings.ai.codex.subprocess.run` (the same double-and-monkeypatch
pattern `tests/support/doubles.py.FakeRun` already established for
`prompts.py`'s fzf lookup); generate/argv tests replace
`etsy_listings.ai.codex.run_managed` so they can assert on exactly what argv,
cwd, and stdin the adapter builds without exercising `ai/process.py`'s own
(separately tested) subprocess machinery.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from etsy_listings.ai import codex
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
    ProviderTask,
    RepairContext,
    SeoRequest,
)
from etsy_listings.ai.process import ProcessResult
from etsy_listings.ai.prompt import RESPONSE_SCHEMA, build_seo_task

_EXEC_HELP = """
Usage: codex exec [OPTIONS] [PROMPT]

Options:
  -s, --sandbox <SANDBOX_MODE>
          [possible values: read-only, workspace-write, danger-full-access]
      --ephemeral
          Run without persisting session files to disk
      --output-schema <FILE>
          Path to a JSON Schema file describing the model's final response shape
  -o, --output-last-message <FILE>
          Specifies file where the last message from the agent should be written
"""


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


def _provider(tmp_path: Path, *, binary: str = "codex") -> codex.CodexProvider:
    return codex.CodexProvider(workspace_root=tmp_path, binary=binary)


def _task(tmp_path: Path) -> ProviderTask:
    """An ordinary SEO task, assembled the way `ui/api/seo.py` assembles one.

    The adapter no longer reads a prompt file (PRD 68), so the seller prose
    is a plain string here rather than something a fixture has to write to
    disk -- which is the whole point of the change: an adapter test can say
    what the CLI is asked to run without staging a workspace.
    """
    return build_seo_task("Write great SEO copy.", _request(tmp_path))


# --------------------------------------------------------------- readiness


class _FakeRun:
    """Answers `subprocess.run` calls from a `{argv-prefix: CompletedProcess}`
    table, keyed on the first two argv elements -- enough to distinguish
    `codex login status` from `codex exec --help` without depending on exact
    flag ordering."""

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
    monkeypatch.setattr(codex.shutil, "which", lambda name: None)
    provider = _provider(tmp_path)

    readiness = provider.readiness()

    assert readiness == ProviderReadiness(ready=False, reason="codex was not found on PATH")


def test_readiness_fails_when_not_authenticated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(codex.shutil, "which", lambda name: "/usr/bin/codex")
    fake = _FakeRun({("login", "status"): subprocess.CompletedProcess([], 1, stdout="", stderr="")})
    monkeypatch.setattr(codex.subprocess, "run", fake)
    provider = _provider(tmp_path)

    readiness = provider.readiness()

    assert readiness.ready is False
    assert "login status" in (readiness.reason or "")
    assert fake.calls == [["/usr/bin/codex", "login", "status"]]


def test_readiness_fails_when_login_status_cannot_be_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(codex.shutil, "which", lambda name: "/usr/bin/codex")

    def _raise(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise OSError("boom")

    monkeypatch.setattr(codex.subprocess, "run", _raise)
    provider = _provider(tmp_path)

    readiness = provider.readiness()

    assert readiness.ready is False
    assert "boom" in (readiness.reason or "")


def test_readiness_fails_when_exec_help_is_missing_required_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(codex.shutil, "which", lambda name: "/usr/bin/codex")
    fake = _FakeRun(
        {
            ("login", "status"): _ok(),
            ("exec", "--help"): _ok(stdout="Usage: codex exec [OPTIONS] [PROMPT]\n"),
        }
    )
    monkeypatch.setattr(codex.subprocess, "run", fake)
    provider = _provider(tmp_path)

    readiness = provider.readiness()

    assert readiness.ready is False
    assert "read-only" in (readiness.reason or "") or "sandbox" in (readiness.reason or "")


def test_readiness_fails_when_exec_help_check_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(codex.shutil, "which", lambda name: "/usr/bin/codex")

    def _run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if tuple(argv[1:3]) == ("login", "status"):
            return _ok()
        raise OSError("boom")

    monkeypatch.setattr(codex.subprocess, "run", _run)
    provider = _provider(tmp_path)

    readiness = provider.readiness()

    assert readiness.ready is False
    assert "boom" in (readiness.reason or "")


def test_readiness_fails_when_exec_help_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(codex.shutil, "which", lambda name: "/usr/bin/codex")

    def _run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if tuple(argv[1:3]) == ("login", "status"):
            return _ok()
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="")

    monkeypatch.setattr(codex.subprocess, "run", _run)
    provider = _provider(tmp_path)

    readiness = provider.readiness()

    assert readiness.ready is False
    assert "exec --help" in (readiness.reason or "")


def test_readiness_says_nothing_about_a_prompt_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A workspace with no `prompts/` directory at all still has a ready
    codex (PRD 68). Which prompt a request uses -- and whether that file
    exists -- is the request's business; answering it here said "codex is
    not ready" about a file that has nothing to do with codex, and said it
    twice, since `ui/api/seo.py` checked the same thing itself."""
    monkeypatch.setattr(codex.shutil, "which", lambda name: "/usr/bin/codex")
    fake = _FakeRun({("login", "status"): _ok(), ("exec", "--help"): _ok(stdout=_EXEC_HELP)})
    monkeypatch.setattr(codex.subprocess, "run", fake)

    readiness = codex.CodexProvider(workspace_root=tmp_path).readiness()

    assert readiness == ProviderReadiness(ready=True)


def test_readiness_is_ready_when_every_check_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(codex.shutil, "which", lambda name: "/usr/bin/codex")
    fake = _FakeRun({("login", "status"): _ok(), ("exec", "--help"): _ok(stdout=_EXEC_HELP)})
    monkeypatch.setattr(codex.subprocess, "run", fake)
    provider = _provider(tmp_path)

    assert provider.readiness() == ProviderReadiness(ready=True)


# ------------------------------------------------------------------ generate


def _patch_run_managed(
    monkeypatch: pytest.MonkeyPatch, result: ProcessResult
) -> list[dict[str, Any]]:
    # `generate()` resolves the binary through `shutil.which` (a Windows
    # npm-installed CLI is a `.CMD` shim that bare-name `subprocess.run`
    # cannot launch without `shell=True` -- see `CodexProvider._resolved_binary`),
    # so it must be patched here too, deterministically, rather than left to
    # whatever happens to be on the machine actually running this test suite.
    monkeypatch.setattr(codex.shutil, "which", lambda name: f"/resolved/{name}")
    calls: list[dict[str, Any]] = []

    def fake_run_managed(argv: list[str], **kwargs: Any) -> ProcessResult:
        # The adapter's temp directory (schema file, last-message file) is
        # cleaned up before `generate()` returns, so anything a test wants to
        # inspect about those files has to be captured here, while they still
        # exist -- not after `generate()` has already returned.
        output_path = Path(argv[argv.index("-o") + 1])
        output_path.write_text(result.stdout, encoding="utf-8")
        record: dict[str, Any] = {"argv": list(argv), **kwargs}
        if "--output-schema" in argv:
            schema_path = Path(argv[argv.index("--output-schema") + 1])
            record["schema"] = json.loads(schema_path.read_text(encoding="utf-8"))
        calls.append(record)
        return result

    monkeypatch.setattr(codex, "run_managed", fake_run_managed)
    return calls


def test_generate_builds_the_expected_argv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _patch_run_managed(
        monkeypatch,
        ProcessResult(
            returncode=0, stdout='{"ok": true}', stderr="", timed_out=False, cancelled=False
        ),
    )
    provider = _provider(tmp_path)
    request = _request(tmp_path)
    deadline = Deadline.starting_now(seconds=60)

    result = provider.generate(_task(tmp_path), deadline)

    assert result.provider == "codex"
    assert result.raw_output == '{"ok": true}'
    assert len(calls) == 1
    call = calls[0]
    argv = call["argv"]
    assert argv[0] == "/resolved/codex"  # the shutil.which-resolved path, not the bare name
    assert argv[1] == "exec"
    assert argv[-1] == "-", "the prompt is piped via stdin, not passed as an argv value"
    assert "-s" in argv and argv[argv.index("-s") + 1] == "read-only"
    assert "--ephemeral" in argv
    assert "--skip-git-repo-check" in argv
    assert "-C" in argv and argv[argv.index("-C") + 1] == str(tmp_path)
    assert "-i" in argv and argv[argv.index("-i") + 1] == str(request.design_image)
    assert "--output-schema" in argv
    assert "-o" in argv
    assert call["cwd"] == tmp_path
    assert call["deadline"] is deadline
    assert call["schema"] == RESPONSE_SCHEMA


def test_generate_sends_the_seller_prompt_and_context_over_stdin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _patch_run_managed(
        monkeypatch,
        ProcessResult(returncode=0, stdout="{}", stderr="", timed_out=False, cancelled=False),
    )
    provider = _provider(tmp_path)
    request = _request(tmp_path)

    provider.generate(_task(tmp_path), Deadline.starting_now(seconds=60))

    stdin_text = calls[0]["input_text"]
    assert "Write great SEO copy." in stdin_text
    assert request.brief in stdin_text
    assert '"tags"' in stdin_text  # the response schema is echoed in the prompt text


def test_generate_appends_the_repair_block_when_repairing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _patch_run_managed(
        monkeypatch,
        ProcessResult(returncode=0, stdout="{}", stderr="", timed_out=False, cancelled=False),
    )
    provider = _provider(tmp_path)
    repair = RepairContext(
        prior_raw_output='{"titles": []}', reasons=("titles: expected exactly 3",)
    )

    provider.generate(_task(tmp_path), Deadline.starting_now(seconds=60), repair=repair)

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
        provider.generate(_task(tmp_path), Deadline.starting_now(seconds=60))


def test_generate_raises_timeout_when_the_process_timed_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_run_managed(
        monkeypatch,
        ProcessResult(returncode=None, stdout="", stderr="", timed_out=True, cancelled=False),
    )
    provider = _provider(tmp_path)

    with pytest.raises(ProviderTimeoutError):
        provider.generate(_task(tmp_path), Deadline.starting_now(seconds=60))


def test_generate_classifies_an_availability_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_run_managed(
        monkeypatch,
        ProcessResult(
            returncode=1,
            stdout="",
            stderr="Error: not logged in.",
            timed_out=False,
            cancelled=False,
        ),
    )
    provider = _provider(tmp_path)

    with pytest.raises(ProviderUnavailableError):
        provider.generate(_task(tmp_path), Deadline.starting_now(seconds=60))


def test_generate_classifies_an_unrecognised_failure_as_generation_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_run_managed(
        monkeypatch,
        ProcessResult(
            returncode=1, stdout="", stderr="panic: boom", timed_out=False, cancelled=False
        ),
    )
    provider = _provider(tmp_path)

    with pytest.raises(ProviderGenerationError):
        provider.generate(_task(tmp_path), Deadline.starting_now(seconds=60))
