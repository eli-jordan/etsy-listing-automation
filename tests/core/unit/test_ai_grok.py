"""``ai/grok.py``: the Grok CLI adapter behind `AiProvider`.

Same doubling strategy as `test_ai_claude.py`: a `ScriptedCliHost` answers
the help probe and the managed generate call, and the credential file is a
temporary one. No real `grok` process runs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from etsy_listings.core.ai import grok
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
    RepairContext,
    SeoRequest,
)
from etsy_listings.core.ai.process import ProcessResult
from etsy_listings.core.ai.prompt import RESPONSE_SCHEMA, build_seo_task

from tests.support.cli_host import ScriptedCliHost, completed, finished, never_launched

_HELP_TEXT = """
Options:
  --json-schema <SCHEMA>
  --output-format <OUTPUT_FORMAT>
  --prompt-file <PATH>
  --tools <TOOLS>
  --permission-mode <MODE>
  --no-subagents
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


def _provider(
    tmp_path: Path, host: ScriptedCliHost, *, credentials: Path | None = None
) -> grok.GrokProvider:
    return grok.GrokProvider(workspace_root=tmp_path, host=host, credentials=credentials)


def _task(tmp_path: Path):
    return build_seo_task("Write great SEO copy.", _request(tmp_path))


def _signed_in(tmp_path: Path) -> Path:
    auth = tmp_path / "auth.json"
    auth.write_text('{"token":"x"}', encoding="utf-8")
    return auth


def _installed(help_text: str = _HELP_TEXT) -> ScriptedCliHost:
    return ScriptedCliHost(
        installed={"grok": "/resolved/grok"}, runs={("--help",): completed(help_text)}
    )


def test_readiness_fails_when_the_binary_is_missing(tmp_path: Path) -> None:
    readiness = _provider(tmp_path, ScriptedCliHost()).readiness()
    assert readiness.ready is False
    assert "not found" in (readiness.reason or "")


def test_readiness_fails_when_there_is_no_credential_file(tmp_path: Path) -> None:
    provider = _provider(tmp_path, _installed(), credentials=tmp_path / "missing.json")
    readiness = provider.readiness()
    assert readiness.ready is False
    assert "not authenticated" in (readiness.reason or "")


def test_readiness_fails_when_help_is_missing_required_flags(tmp_path: Path) -> None:
    provider = _provider(tmp_path, _installed("Usage: grok\n"), credentials=_signed_in(tmp_path))
    readiness = provider.readiness()
    assert readiness.ready is False
    assert "json-schema" in (readiness.reason or "")


def test_readiness_is_ready_when_the_credential_and_flags_are_present(tmp_path: Path) -> None:
    host = _installed()
    provider = _provider(tmp_path, host, credentials=_signed_in(tmp_path))
    assert provider.readiness() == ProviderReadiness(ready=True)
    assert host.ran == [["/resolved/grok", "--help"]]


def test_the_default_credential_file_is_grok_logins(tmp_path: Path) -> None:
    assert grok.auth_file() == Path.home() / ".grok" / "auth.json"


class _Grok:
    """`grok` as the adapter sees it. The prompt file is removed once the
    process returns, so its text is read here, during the call."""

    def __init__(self, result: ProcessResult) -> None:
        self.result = result
        self.prompts: list[str] = []

    def __call__(self, argv: list[str], **_: object) -> ProcessResult:
        prompt_path = Path(argv[argv.index("--prompt-file") + 1])
        self.prompts.append(prompt_path.read_text(encoding="utf-8"))
        return self.result


def _generating(cli: _Grok) -> ScriptedCliHost:
    return ScriptedCliHost(installed={"grok": "/resolved/grok"}, managed={(): cli})


def test_generate_writes_the_prompt_to_a_file_and_returns_the_text_field(tmp_path: Path) -> None:
    envelope = json.dumps(
        {"text": '{"ok": true}', "structuredOutput": {"ok": True}, "stopReason": "end_turn"}
    )
    cli = _Grok(finished(envelope))
    host = _generating(cli)
    request = _request(tmp_path)

    result = _provider(tmp_path, host).generate(_task(tmp_path), Deadline.starting_now(seconds=60))

    assert result.provider == "grok"
    assert result.raw_output == '{"ok": true}'
    argv = host.last_managed.argv
    assert argv[0] == "/resolved/grok"
    assert "--prompt-file" in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert json.loads(argv[argv.index("--json-schema") + 1]) == RESPONSE_SCHEMA
    assert argv[argv.index("--tools") + 1] == "read_file,grep,list_dir"
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert "--no-subagents" in argv
    assert "--verbatim" in argv
    assert "-p" not in argv
    prompt = cli.prompts[0]
    assert "Write great SEO copy." in prompt
    assert request.brief in prompt
    assert str(request.design_image) in prompt
    assert "read_file" in prompt
    # The temp prompt is removed once the process returns.
    assert not Path(argv[argv.index("--prompt-file") + 1]).exists()


def test_generate_uses_the_schema_object_when_the_text_is_not_json(tmp_path: Path) -> None:
    # `--json-schema` puts the valid object in `structuredOutput`. `text` is
    # the model's own write-up and is not required to parse.
    envelope = json.dumps(
        {
            "text": 'Here is the proposal:\n```json\n{"ok": false}\n```',
            "structuredOutput": {"ok": True},
            "stopReason": "end_turn",
        }
    )
    host = _generating(_Grok(finished(envelope)))

    result = _provider(tmp_path, host).generate(_task(tmp_path), Deadline.starting_now(seconds=60))

    assert json.loads(result.raw_output) == {"ok": True}


def test_generate_falls_back_to_structured_output_when_text_is_missing(tmp_path: Path) -> None:
    envelope = json.dumps({"structuredOutput": {"ok": True}, "stopReason": "end_turn"})
    host = _generating(_Grok(finished(envelope)))

    result = _provider(tmp_path, host).generate(_task(tmp_path), Deadline.starting_now(seconds=60))

    assert json.loads(result.raw_output) == {"ok": True}


def test_generate_appends_the_repair_block(tmp_path: Path) -> None:
    cli = _Grok(finished(json.dumps({"text": "{}"})))
    repair = RepairContext(
        prior_raw_output='{"titles": []}', reasons=("titles: expected exactly 3",)
    )

    _provider(tmp_path, _generating(cli)).generate(
        _task(tmp_path), Deadline.starting_now(seconds=60), repair=repair
    )

    assert '{"titles": []}' in cli.prompts[0]
    assert "titles: expected exactly 3" in cli.prompts[0]


@pytest.mark.parametrize(
    ("result", "error"),
    [
        (finished(stderr="Error: not authenticated", returncode=1), ProviderUnavailableError),
        (ProcessResult(None, "", "", timed_out=True, cancelled=False), ProviderTimeoutError),
        (ProcessResult(None, "", "", timed_out=False, cancelled=True), ProviderCancelledError),
        (finished("not json"), ProviderGenerationError),
    ],
    ids=["nonzero-exit", "timed-out", "cancelled", "unparseable"],
)
def test_generate_classifies_how_the_process_ended(
    tmp_path: Path, result: ProcessResult, error: type[Exception]
) -> None:
    with pytest.raises(error):
        _provider(tmp_path, _generating(_Grok(result))).generate(
            _task(tmp_path), Deadline.starting_now(seconds=60)
        )


def test_generate_with_no_binary_is_unavailable(tmp_path: Path) -> None:
    host = ScriptedCliHost(managed={(): never_launched})

    with pytest.raises(ProviderUnavailableError, match="grok was not found on PATH"):
        _provider(tmp_path, host).generate(_task(tmp_path), Deadline.starting_now(seconds=60))
