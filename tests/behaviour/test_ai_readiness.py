"""AI readiness, asked directly (features/market-seo-20260924/spec.md, *AI
runs*; batch-creation spec, *Design validation*; module-structure plan, PR 9).

Whether a run may start for a listing, and whether a batch created now could
draft, without a request or a running server: the rules the **AI Mode**
button, ``POST /api/ai/runs`` and staging's *AI drafting can't run yet*
all answer with. The HTTP mapping of these answers is
``tests/contract/test_ai_seo_api.py``'s and ``test_batches_api.py``'s.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.core.ai.models import ProviderReadiness
from etsy_listings.core.ai.providers import AiProvider, FakeAiProvider
from etsy_listings.core.application.ai.readiness import (
    AiReadinessBlock,
    batch_blocked,
    default_ai_providers,
    unready_reason,
)
from etsy_listings.core.workspace.layout import (
    BRIEF_PROMPT_FILE,
    MARKET_QUERIES_PROMPT_FILE,
    PROMPTS_DIR,
    SEO_PROMPT_FILE,
)
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.ai_runs import seed_prompts
from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import edit_listing

READY: list[AiProvider] = [FakeAiProvider(name="codex", ready=ProviderReadiness(ready=True))]


def _unready(name: str, reason: str) -> FakeAiProvider:
    return FakeAiProvider(name=name, ready=ProviderReadiness(ready=False, reason=reason))


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    seed_prompts(workspace_root)
    return Workspace.discover(root_override=workspace_root)


def _reason(
    workspace: Workspace, providers: list[AiProvider] = READY, *, draft_brief: bool = True
) -> str | None:
    return unready_reason(
        workspace, workspace.load_listing(LISTING), providers, draft_brief=draft_brief
    )


# ------------------------------------------------------------- one listing


def test_a_listing_with_everything_a_run_reads_is_ready(workspace: Workspace) -> None:
    providers: list[AiProvider] = [_unready("codex", "not signed in"), *READY]

    assert _reason(workspace, providers) is None


@pytest.mark.parametrize("prompt", [SEO_PROMPT_FILE, MARKET_QUERIES_PROMPT_FILE])
def test_both_prompts_every_run_reads_are_needed(
    workspace: Workspace, workspace_root: Path, prompt: str
) -> None:
    (workspace_root / PROMPTS_DIR / prompt).unlink()

    reason = _reason(workspace)

    assert reason is not None
    assert prompt in reason
    assert reason.endswith("is missing; run `etsy-listings setup` to seed it")


def test_a_listing_without_a_design_is_not_ready(
    workspace: Workspace, workspace_root: Path
) -> None:
    edit_listing(workspace_root, design={})

    assert _reason(workspace) == "the listing has no selected design"


def test_an_empty_brief_is_ready_only_for_a_run_that_drafts_it(
    workspace: Workspace, workspace_root: Path
) -> None:
    edit_listing(workspace_root, brief="   ")

    assert _reason(workspace, draft_brief=True) is None
    assert _reason(workspace, draft_brief=False) == "the listing brief is empty"


def test_drafting_an_empty_brief_needs_the_brief_prompt(
    workspace: Workspace, workspace_root: Path
) -> None:
    (workspace_root / PROMPTS_DIR / BRIEF_PROMPT_FILE).unlink()
    assert _reason(workspace) is None, "a written brief is not drafted, so needs no prompt"

    edit_listing(workspace_root, brief="")

    reason = _reason(workspace)
    assert reason is not None and BRIEF_PROMPT_FILE in reason


def test_a_listing_without_a_usable_garment_profile_is_not_ready(
    workspace: Workspace, workspace_root: Path
) -> None:
    edit_listing(workspace_root, garment_profile="no-such-profile")

    assert _reason(workspace) == "the listing has no usable garment profile"


def test_no_ready_provider_names_every_provider_s_reason(workspace: Workspace) -> None:
    providers: list[AiProvider] = [
        _unready("codex", "codex is not authenticated"),
        _unready("claude", "claude was not found on PATH"),
    ]

    assert _reason(workspace, providers) == (
        "no AI provider is ready (codex is not authenticated; claude was not found on PATH)"
    )


def test_the_listing_s_own_gaps_are_named_before_the_machine_s(
    workspace: Workspace, workspace_root: Path
) -> None:
    edit_listing(workspace_root, design={})

    assert _reason(workspace, [_unready("codex", "nope")]) == "the listing has no selected design"


# ------------------------------------------------------------ a new batch


def test_a_batch_can_draft_with_the_prompts_a_provider_and_market_access(
    workspace: Workspace,
) -> None:
    assert batch_blocked(workspace, READY, has_market=True) is None


def test_a_batch_names_the_first_missing_prompt_by_its_workspace_path(
    workspace: Workspace, workspace_root: Path
) -> None:
    (workspace_root / PROMPTS_DIR / BRIEF_PROMPT_FILE).unlink()

    assert batch_blocked(workspace, READY, has_market=True) == AiReadinessBlock(
        message=f"{PROMPTS_DIR}/{BRIEF_PROMPT_FILE} is missing.",
        remedy="Run `etsy-listings setup` to seed it, then come back. Your staging is kept.",
    )


def test_a_batch_needs_a_ready_provider(workspace: Workspace) -> None:
    assert batch_blocked(workspace, [_unready("codex", "nope")], has_market=True) == (
        AiReadinessBlock(
            message="No AI provider is ready.",
            remedy="Add one in Setup, then come back. Your staging is kept.",
        )
    )


def test_a_batch_needs_etsy_market_access(workspace: Workspace) -> None:
    assert batch_blocked(workspace, READY, has_market=False) == AiReadinessBlock(
        message="Etsy market access isn't set up.",
        remedy="Add the Etsy app key in Setup, then come back. Your staging is kept.",
    )


# ------------------------------------------------------- provider selection


def test_the_default_providers_are_codex_then_claude_then_grok(workspace: Workspace) -> None:
    providers = default_ai_providers(workspace)

    assert [type(p).__name__ for p in providers] == [
        "CodexProvider",
        "ClaudeProvider",
        "GrokProvider",
    ]
