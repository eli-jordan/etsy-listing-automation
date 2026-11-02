"""``ai/codex.py``: the Codex CLI adapter behind `AiProvider` (AI SEO
implementation plan, PR4, items 1-4).

Nothing here launches a real `codex` process. Every provider is built on a
`tests/support/cli_host.py.ScriptedCliHost`: readiness tests script the
probes' answers, generate/argv tests script the managed run, so they can
assert on exactly what argv, cwd, and stdin the adapter builds without
exercising `ai/process.py`'s own (separately tested) subprocess machinery.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from etsy_listings.core.ai import codex
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
from etsy_listings.core.ai.process import ProcessResult
from etsy_listings.core.ai.prompt import RESPONSE_SCHEMA, build_seo_task

from tests.support.cli_host import (
    RunAnswer,
    ScriptedCliHost,
    completed,
    finished,
    never_launched,
)

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


def _provider(tmp_path: Path, host: ScriptedCliHost) -> codex.CodexProvider:
    return codex.CodexProvider(workspace_root=tmp_path, host=host)


def _task(tmp_path: Path) -> ProviderTask:
    """An ordinary SEO task, assembled the way `server/api/seo.py` assembles one.

    The adapter no longer reads a prompt file, so the seller prose
    is a plain string here rather than something a fixture has to write to
    disk -- which is the whole point of the change: an adapter test can say
    what the CLI is asked to run without staging a workspace.
    """
    return build_seo_task("Write great SEO copy.", _request(tmp_path))


# --------------------------------------------------------------- readiness


def _installed(runs: dict[tuple[str, ...], RunAnswer]) -> ScriptedCliHost:
    """`codex` on PATH, its probes answering from ``runs``."""
    return ScriptedCliHost(installed={"codex": "/usr/bin/codex"}, runs=runs)


def test_readiness_fails_when_executable_is_missing(tmp_path: Path) -> None:
    readiness = _provider(tmp_path, ScriptedCliHost()).readiness()

    assert readiness == ProviderReadiness(ready=False, reason="codex was not found on PATH")


def test_readiness_fails_when_not_authenticated(tmp_path: Path) -> None:
    host = _installed({("login", "status"): completed(returncode=1)})

    readiness = _provider(tmp_path, host).readiness()

    assert readiness.ready is False
    assert "login status" in (readiness.reason or "")
    assert host.ran == [["/usr/bin/codex", "login", "status"]]


def test_readiness_fails_when_login_status_cannot_be_run(tmp_path: Path) -> None:
    host = _installed({("login", "status"): OSError("boom")})

    readiness = _provider(tmp_path, host).readiness()

    assert readiness.ready is False
    assert "boom" in (readiness.reason or "")


def test_readiness_fails_when_exec_help_is_missing_required_flags(tmp_path: Path) -> None:
    host = _installed(
        {
            ("login", "status"): completed(),
            ("exec", "--help"): completed("Usage: codex exec [OPTIONS] [PROMPT]\n"),
        }
    )

    readiness = _provider(tmp_path, host).readiness()

    assert readiness.ready is False
    assert "read-only" in (readiness.reason or "") or "sandbox" in (readiness.reason or "")


def test_readiness_fails_when_exec_help_check_raises(tmp_path: Path) -> None:
    host = _installed({("login", "status"): completed(), ("exec", "--help"): OSError("boom")})

    readiness = _provider(tmp_path, host).readiness()

    assert readiness.ready is False
    assert "boom" in (readiness.reason or "")


def test_readiness_fails_when_exec_help_exits_nonzero(tmp_path: Path) -> None:
    host = _installed(
        {("login", "status"): completed(), ("exec", "--help"): completed(returncode=1)}
    )

    readiness = _provider(tmp_path, host).readiness()

    assert readiness.ready is False
    assert "exec --help" in (readiness.reason or "")


def test_readiness_says_nothing_about_a_prompt_file(tmp_path: Path) -> None:
    """A workspace with no `prompts/` directory at all still has a ready
    codex. Which prompt a request uses -- and whether that file
    exists -- is the request's business; answering it here said "codex is
    not ready" about a file that has nothing to do with codex, and said it
    twice, since `server/api/seo.py` checked the same thing itself."""
    host = _installed({("login", "status"): completed(), ("exec", "--help"): completed(_EXEC_HELP)})

    readiness = codex.CodexProvider(workspace_root=tmp_path, host=host).readiness()

    assert readiness == ProviderReadiness(ready=True)


def test_readiness_is_ready_when_every_check_passes(tmp_path: Path) -> None:
    host = _installed({("login", "status"): completed(), ("exec", "--help"): completed(_EXEC_HELP)})

    assert _provider(tmp_path, host).readiness() == ProviderReadiness(ready=True)


# ------------------------------------------------------------------ generate


class _Codex:
    """`codex exec` as the adapter sees it: the last message lands in the
    ``-o`` file. The adapter's temp directory (schema file, last-message
    file) is cleaned up before `generate()` returns, so anything a test wants
    to inspect about those files is captured here, while they still exist."""

    def __init__(self, result: ProcessResult) -> None:
        self.result = result
        self.schemas: list[object] = []

    def __call__(self, argv: list[str], **_: object) -> ProcessResult:
        Path(argv[argv.index("-o") + 1]).write_text(self.result.stdout, encoding="utf-8")
        schema_path = Path(argv[argv.index("--output-schema") + 1])
        self.schemas.append(json.loads(schema_path.read_text(encoding="utf-8")))
        return self.result


def _generating(cli: _Codex) -> ScriptedCliHost:
    # `generate()` resolves the binary through `which` (a Windows
    # npm-installed CLI is a `.CMD` shim that a bare name cannot launch
    # without `shell=True` -- see `LocalCliProvider._resolved_binary`).
    return ScriptedCliHost(installed={"codex": "/resolved/codex"}, managed={(): cli})


def test_generate_builds_the_expected_argv(tmp_path: Path) -> None:
    cli = _Codex(finished('{"ok": true}'))
    host = _generating(cli)
    request = _request(tmp_path)
    deadline = Deadline.starting_now(seconds=60)

    result = _provider(tmp_path, host).generate(_task(tmp_path), deadline)

    assert result.provider == "codex"
    assert result.raw_output == '{"ok": true}'
    assert len(host.managed_calls) == 1
    call = host.last_managed
    argv = call.argv
    assert argv[0] == "/resolved/codex"  # the which-resolved path, not the bare name
    assert argv[1] == "exec"
    assert argv[-1] == "-", "the prompt is piped via stdin, not passed as an argv value"
    assert "-s" in argv
    assert argv[argv.index("-s") + 1] == "read-only"
    assert "--ephemeral" in argv
    assert "--skip-git-repo-check" in argv
    assert "-C" in argv
    assert argv[argv.index("-C") + 1] == str(tmp_path)
    assert "-i" in argv
    assert argv[argv.index("-i") + 1] == str(request.design_image)
    assert "--output-schema" in argv
    assert "-o" in argv
    assert call.cwd == tmp_path
    assert call.deadline is deadline
    assert cli.schemas == [RESPONSE_SCHEMA]


def test_generate_sends_the_seller_prompt_and_context_over_stdin(tmp_path: Path) -> None:
    host = _generating(_Codex(finished("{}")))
    request = _request(tmp_path)

    _provider(tmp_path, host).generate(_task(tmp_path), Deadline.starting_now(seconds=60))

    stdin_text = host.last_managed.input_text
    assert "Write great SEO copy." in stdin_text
    assert request.brief in stdin_text
    assert '"tags"' in stdin_text  # the response schema is echoed in the prompt text


def test_generate_appends_the_repair_block_when_repairing(tmp_path: Path) -> None:
    host = _generating(_Codex(finished("{}")))
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
        # An availability failure, recognised by its text.
        (finished(stderr="Error: not logged in.", returncode=1), ProviderUnavailableError),
        (finished(stderr="panic: boom", returncode=1), ProviderGenerationError),
    ],
    ids=["cancelled", "timed-out", "unavailable", "unrecognised"],
)
def test_generate_classifies_how_the_process_ended(
    tmp_path: Path, result: ProcessResult, error: type[Exception]
) -> None:
    host = _generating(_Codex(result))

    with pytest.raises(error):
        _provider(tmp_path, host).generate(_task(tmp_path), Deadline.starting_now(seconds=60))


def test_generate_with_no_binary_on_path_is_unavailable_so_the_next_provider_runs(
    tmp_path: Path,
) -> None:
    # A machine with only one of the two CLIs installed. Launching the bare
    # name fails with WinError 2, which is not an availability failure the
    # orchestrator falls through on -- it used to end the whole run.
    host = ScriptedCliHost(managed={(): never_launched})

    with pytest.raises(ProviderUnavailableError, match="codex was not found on PATH"):
        _provider(tmp_path, host).generate(_task(tmp_path), Deadline.starting_now(seconds=60))
