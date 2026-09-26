"""``ai/grok.py``: the Grok CLI adapter behind `AiProvider`.

Same doubling strategy as `test_ai_claude.py`: `subprocess.run` is replaced
for the help check, `run_managed` for generate. No real `grok` process runs.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from etsy_listings.ai import grok
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
from etsy_listings.ai.prompt import RESPONSE_SCHEMA, build_seo_task

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


def _provider(tmp_path: Path) -> grok.GrokProvider:
    return grok.GrokProvider(workspace_root=tmp_path, binary="grok")


def _task(tmp_path: Path):
    return build_seo_task("Write great SEO copy.", _request(tmp_path))


def _ok(stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["grok"], 0, stdout=stdout, stderr="")


def _patch_ready(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, help_text: str = _HELP_TEXT
) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text('{"token":"x"}', encoding="utf-8")
    monkeypatch.setattr(grok, "auth_file", lambda: auth)
    monkeypatch.setattr(grok.shutil, "which", lambda name: f"/resolved/{name}")

    def _run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _ok(stdout=help_text)

    monkeypatch.setattr(grok.subprocess, "run", _run)


def test_readiness_fails_when_the_binary_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(grok.shutil, "which", lambda name: None)
    readiness = _provider(tmp_path).readiness()
    assert readiness.ready is False
    assert "not found" in (readiness.reason or "")


def test_readiness_fails_when_there_is_no_credential_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(grok, "auth_file", lambda: tmp_path / "missing.json")
    monkeypatch.setattr(grok.shutil, "which", lambda name: "/resolved/grok")
    readiness = _provider(tmp_path).readiness()
    assert readiness.ready is False
    assert "not authenticated" in (readiness.reason or "")


def test_readiness_fails_when_help_is_missing_required_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_ready(monkeypatch, tmp_path, help_text="Usage: grok\n")
    readiness = _provider(tmp_path).readiness()
    assert readiness.ready is False
    assert "json-schema" in (readiness.reason or "")


def test_readiness_is_ready_when_the_credential_and_flags_are_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_ready(monkeypatch, tmp_path)
    assert _provider(tmp_path).readiness() == ProviderReadiness(ready=True)


def _patch_generate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, result: ProcessResult
) -> list[dict[str, Any]]:
    monkeypatch.setattr(grok.shutil, "which", lambda name: f"/resolved/{name}")
    calls: list[dict[str, Any]] = []

    def fake_run_managed(argv: list[str], **kwargs: Any) -> ProcessResult:
        prompt_path = Path(argv[argv.index("--prompt-file") + 1])
        calls.append(
            {"argv": list(argv), "prompt": prompt_path.read_text(encoding="utf-8"), **kwargs}
        )
        return result

    monkeypatch.setattr(grok, "run_managed", fake_run_managed)
    return calls


def test_generate_writes_the_prompt_to_a_file_and_returns_the_text_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    envelope = json.dumps(
        {"text": '{"ok": true}', "structuredOutput": {"ok": True}, "stopReason": "end_turn"}
    )
    calls = _patch_generate(
        monkeypatch,
        tmp_path,
        ProcessResult(returncode=0, stdout=envelope, stderr="", timed_out=False, cancelled=False),
    )
    request = _request(tmp_path)

    result = _provider(tmp_path).generate(_task(tmp_path), Deadline.starting_now(seconds=60))

    assert result.provider == "grok"
    assert result.raw_output == '{"ok": true}'
    argv = calls[0]["argv"]
    assert argv[0] == "/resolved/grok"
    assert "--prompt-file" in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert json.loads(argv[argv.index("--json-schema") + 1]) == RESPONSE_SCHEMA
    assert argv[argv.index("--tools") + 1] == "read_file,grep,list_dir"
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert "--no-subagents" in argv
    assert "--verbatim" in argv
    assert "-p" not in argv
    prompt = calls[0]["prompt"]
    assert "Write great SEO copy." in prompt
    assert request.brief in prompt
    assert str(request.design_image) in prompt
    assert "read_file" in prompt
    # The temp prompt is removed once the process returns.
    assert not Path(argv[argv.index("--prompt-file") + 1]).exists()


def test_generate_uses_the_schema_object_when_the_text_is_not_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # `--json-schema` puts the valid object in `structuredOutput`. `text` is
    # the model's own write-up and is not required to parse.
    envelope = json.dumps(
        {
            "text": 'Here is the proposal:\n```json\n{"ok": false}\n```',
            "structuredOutput": {"ok": True},
            "stopReason": "end_turn",
        }
    )
    _patch_generate(
        monkeypatch,
        tmp_path,
        ProcessResult(returncode=0, stdout=envelope, stderr="", timed_out=False, cancelled=False),
    )

    result = _provider(tmp_path).generate(_task(tmp_path), Deadline.starting_now(seconds=60))

    assert json.loads(result.raw_output) == {"ok": True}


def test_generate_falls_back_to_structured_output_when_text_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    envelope = json.dumps({"structuredOutput": {"ok": True}, "stopReason": "end_turn"})
    _patch_generate(
        monkeypatch,
        tmp_path,
        ProcessResult(returncode=0, stdout=envelope, stderr="", timed_out=False, cancelled=False),
    )

    result = _provider(tmp_path).generate(_task(tmp_path), Deadline.starting_now(seconds=60))

    assert json.loads(result.raw_output) == {"ok": True}


def test_generate_appends_the_repair_block(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    envelope = json.dumps({"text": "{}"})
    calls = _patch_generate(
        monkeypatch,
        tmp_path,
        ProcessResult(returncode=0, stdout=envelope, stderr="", timed_out=False, cancelled=False),
    )
    repair = RepairContext(
        prior_raw_output='{"titles": []}', reasons=("titles: expected exactly 3",)
    )

    _provider(tmp_path).generate(_task(tmp_path), Deadline.starting_now(seconds=60), repair=repair)

    assert '{"titles": []}' in calls[0]["prompt"]
    assert "titles: expected exactly 3" in calls[0]["prompt"]


def test_generate_classifies_a_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_generate(
        monkeypatch,
        tmp_path,
        ProcessResult(
            returncode=1,
            stdout="",
            stderr="Error: not authenticated",
            timed_out=False,
            cancelled=False,
        ),
    )

    with pytest.raises(ProviderUnavailableError):
        _provider(tmp_path).generate(_task(tmp_path), Deadline.starting_now(seconds=60))


def test_generate_raises_timeout_and_cancelled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_generate(
        monkeypatch,
        tmp_path,
        ProcessResult(returncode=None, stdout="", stderr="", timed_out=True, cancelled=False),
    )
    with pytest.raises(ProviderTimeoutError):
        _provider(tmp_path).generate(_task(tmp_path), Deadline.starting_now(seconds=60))

    _patch_generate(
        monkeypatch,
        tmp_path,
        ProcessResult(returncode=None, stdout="", stderr="", timed_out=False, cancelled=True),
    )
    with pytest.raises(ProviderCancelledError):
        _provider(tmp_path).generate(_task(tmp_path), Deadline.starting_now(seconds=60))


def test_generate_with_no_binary_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(grok.shutil, "which", lambda name: None)

    def never_launched(argv: list[str], **kwargs: Any) -> ProcessResult:
        raise AssertionError("a missing binary must not be launched")

    monkeypatch.setattr(grok, "run_managed", never_launched)

    with pytest.raises(ProviderUnavailableError, match="grok was not found on PATH"):
        _provider(tmp_path).generate(_task(tmp_path), Deadline.starting_now(seconds=60))


def test_unparseable_stdout_is_a_generation_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_generate(
        monkeypatch,
        tmp_path,
        ProcessResult(returncode=0, stdout="not json", stderr="", timed_out=False, cancelled=False),
    )
    with pytest.raises(ProviderGenerationError):
        _provider(tmp_path).generate(_task(tmp_path), Deadline.starting_now(seconds=60))
