"""ADR-0056 preferences through the provider factory and subprocess boundary."""

import json
from pathlib import Path

import pytest

from etsy_listings.core.ai import claude, codex, grok
from etsy_listings.core.ai.models import Deadline, ProviderTask, RepairContext
from etsy_listings.core.ai.process import ProcessResult
from etsy_listings.core.application.ai.readiness import default_ai_providers
from etsy_listings.core.workspace import Workspace


def test_factory_captures_order_and_preferences_until_next_call(workspace_root: Path) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    workspace.settings_file().write_text(
        "ai:\n  providers:\n    - name: grok\n      model: retired\n      effort: high\n"
        "    - name: codex\n      enabled: false\n    - name: claude\n"
    )
    captured = default_ai_providers(workspace)
    assert [type(p).__name__ for p in captured] == ["GrokProvider", "ClaudeProvider"]
    assert captured[0].model == "retired"
    assert captured[0].effort == "high"
    workspace.settings_file().write_text("ai:\n  providers: [{name: codex}]\n")
    assert [type(p).__name__ for p in default_ai_providers(workspace)] == ["CodexProvider"]
    assert captured[0].model == "retired"


@pytest.mark.parametrize(
    ("module", "adapter", "flags"),
    [
        (
            codex,
            codex.CodexProvider,
            ["--model", "saved-model", "-c", 'model_reasoning_effort="saved-effort"'],
        ),
        (claude, claude.ClaudeProvider, ["--model", "saved-model", "--effort", "saved-effort"]),
        (grok, grok.GrokProvider, ["--model", "saved-model", "--reasoning-effort", "saved-effort"]),
    ],
)
@pytest.mark.parametrize("repair", [None, RepairContext("{}", ("missing brief",))])
def test_preferences_reach_every_task_and_repair_argv(
    module, adapter, flags, monkeypatch, tmp_path, repair
):
    calls = []
    monkeypatch.setattr(module.shutil, "which", lambda name: name)

    def execute(argv, **kwargs):
        calls.append(argv)
        return ProcessResult(
            returncode=0,
            stdout=json.dumps({"result": "{}", "structuredOutput": {}}),
            stderr="",
            timed_out=False,
            cancelled=False,
        )

    monkeypatch.setattr(module, "run_managed", execute)
    task = ProviderTask(
        prompt_text="Read design", response_schema={}, design_image=tmp_path / "design.png"
    )
    provider = adapter(workspace_root=tmp_path, model="saved-model", effort="saved-effort")
    provider.generate(task, Deadline.starting_now(seconds=300), repair=repair)
    assert calls[0][-len(flags) :] == flags
    assert "--service-tier" not in calls[0]
    calls.clear()
    adapter(workspace_root=tmp_path).generate(
        task, Deadline.starting_now(seconds=300), repair=repair
    )
    assert not any(flag in calls[0] for flag in ["--model", "--effort", "--reasoning-effort", "-c"])


def test_a_rejected_saved_model_falls_through_without_rewriting_preferences(
    workspace_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from etsy_listings.core.ai.brief import BriefRequest
    from etsy_listings.core.ai.orchestrator import generate_brief

    workspace = Workspace.discover(root_override=workspace_root)
    source = "ai:\n  providers: [{name: codex, model: retired}, {name: claude, model: pinned}]\n"
    workspace.settings_file().write_text(source)
    calls = []
    monkeypatch.setattr(codex.shutil, "which", lambda name: name)

    def rejected(argv, **kwargs):
        calls.append(argv)
        return ProcessResult(1, "", "Unknown model: retired", False, False)

    def fallback(argv, **kwargs):
        calls.append(argv)
        return ProcessResult(
            0, json.dumps({"result": json.dumps({"brief": "A sunset design."})}), "", False, False
        )

    monkeypatch.setattr(codex, "run_managed", rejected)
    monkeypatch.setattr(claude, "run_managed", fallback)
    result = generate_brief(
        BriefRequest(design_image=workspace_root / "design.png"),
        "Read artwork",
        default_ai_providers(workspace),
    )
    assert result.brief == "A sunset design."
    assert [argv[argv.index("--model") + 1] for argv in calls] == ["retired", "pinned"]
    assert workspace.settings_file().read_text() == source
