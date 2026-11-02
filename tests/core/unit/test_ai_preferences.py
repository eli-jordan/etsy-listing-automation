"""ADR-0056 preferences through the provider factory and subprocess boundary."""

import json
from functools import partial
from pathlib import Path

import pytest

from etsy_listings.core.ai import claude, codex, grok
from etsy_listings.core.ai.models import Deadline, ProviderTask, RepairContext
from etsy_listings.core.application.ai.readiness import current_providers, default_ai_providers
from etsy_listings.core.workspace import Workspace

from tests.support.cli_host import ScriptedCliHost, finished


def test_factory_captures_order_and_preferences_until_next_call(workspace_root: Path) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    workspace.settings_file().write_text(
        "ai:\n  providers:\n    - name: grok\n      model: retired\n      effort: high\n"
        "    - name: codex\n      enabled: false\n    - name: claude\n"
    )
    captured = current_providers(default_ai_providers, workspace)
    assert [type(p).__name__ for p in captured] == ["GrokProvider", "ClaudeProvider"]
    assert captured[0].model == "retired"
    assert captured[0].effort == "high"
    workspace.settings_file().write_text("ai:\n  providers: [{name: codex}]\n")
    assert [type(p).__name__ for p in current_providers(default_ai_providers, workspace)] == [
        "CodexProvider"
    ]
    assert captured[0].model == "retired"


@pytest.mark.parametrize(
    ("adapter", "flags"),
    [
        (
            codex.CodexProvider,
            ["--model", "saved-model", "-c", 'model_reasoning_effort="saved-effort"'],
        ),
        (claude.ClaudeProvider, ["--model", "saved-model", "--effort", "saved-effort"]),
        (grok.GrokProvider, ["--model", "saved-model", "--reasoning-effort", "saved-effort"]),
    ],
)
@pytest.mark.parametrize("repair", [None, RepairContext("{}", ("missing brief",))])
def test_preferences_reach_every_task_and_repair_argv(adapter, flags, *, tmp_path, repair):
    answer = finished(json.dumps({"result": "{}", "structuredOutput": {}}))
    host = ScriptedCliHost(
        installed={name: name for name in ("codex", "claude", "grok")}, managed={(): answer}
    )
    task = ProviderTask(
        prompt_text="Read design", response_schema={}, design_image=tmp_path / "design.png"
    )
    provider = adapter(
        workspace_root=tmp_path, model="saved-model", effort="saved-effort", host=host
    )
    provider.generate(task, Deadline.starting_now(seconds=300), repair=repair)
    argv = host.last_managed.argv
    assert argv[-len(flags) :] == flags
    assert "--service-tier" not in argv
    adapter(workspace_root=tmp_path, host=host).generate(
        task, Deadline.starting_now(seconds=300), repair=repair
    )
    argv = host.last_managed.argv
    assert not any(flag in argv for flag in ["--model", "--effort", "--reasoning-effort", "-c"])


def test_a_rejected_saved_model_falls_through_without_rewriting_preferences(
    workspace_root: Path,
) -> None:
    from etsy_listings.core.ai.brief import BriefRequest
    from etsy_listings.core.ai.orchestrator import generate_brief

    workspace = Workspace.discover(root_override=workspace_root)
    source = "ai:\n  providers: [{name: codex, model: retired}, {name: claude, model: pinned}]\n"
    workspace.settings_file().write_text(source)
    host = ScriptedCliHost(
        installed={"codex": "codex", "claude": "claude"},
        managed={
            ("exec",): finished(stderr="Unknown model: retired", returncode=1),
            ("-p",): finished(json.dumps({"result": json.dumps({"brief": "A sunset design."})})),
        },
    )
    result = generate_brief(
        BriefRequest(design_image=workspace_root / "design.png"),
        "Read artwork",
        current_providers(partial(default_ai_providers, host=host), workspace),
    )
    assert result.brief == "A sunset design."
    models = [call.argv[call.argv.index("--model") + 1] for call in host.managed_calls]
    assert models == ["retired", "pinned"]
    assert workspace.settings_file().read_text() == source
