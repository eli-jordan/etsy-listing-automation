"""``GET /api/listings/{name}/ai-seo/readiness``: whether the **AI Mode**
button may start a run (market-seo.md, *AI runs*; implementation plan, PR 6).

The button drafts a brief when the saved one is empty, so readiness answers
with the rules ``POST /api/ai/runs`` applies to ``draft_brief=true``: a
design, a usable garment profile, ``prompts/seo.md`` and
``prompts/market-queries.md``, a ready provider, and -- only while the brief
is empty -- ``prompts/brief.md``. A button that lit up for a run the server
would then refuse was the gap this closes.

The two generation endpoints that used to live beside it are retired; AI
runs replaced both (``test_ai_runs_api.py``).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from etsy_listings.ai.models import ProviderReadiness
from etsy_listings.ai.providers import AiProvider, FakeAiProvider
from etsy_listings.ui.api.app import create_app
from etsy_listings.workspace.layout import (
    BRIEF_PROMPT_FILE,
    MARKET_QUERIES_PROMPT_FILE,
    PROMPTS_DIR,
    SEO_PROMPT_FILE,
)
from etsy_listings.workspace.workspace import Workspace

from tests.support.ai_runs import seed_prompts
from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import edit_listing

READINESS = f"/api/listings/{LISTING}/ai-seo/readiness"


def _ready_provider(name: str = "codex") -> FakeAiProvider:
    return FakeAiProvider(name=name, ready=ProviderReadiness(ready=True))


def _unready_provider(name: str, reason: str) -> FakeAiProvider:
    return FakeAiProvider(name=name, ready=ProviderReadiness(ready=False, reason=reason))


@contextmanager
def _client(workspace_root: Path, providers: list[AiProvider]) -> Iterator[TestClient]:
    workspace = Workspace.discover(root_override=workspace_root)
    app = create_app(workspace, seo_provider_factory=lambda _workspace: providers)
    with TestClient(app) as test_client:
        yield test_client


def _readiness(
    workspace_root: Path, providers: list[AiProvider] | None = None
) -> dict[str, object]:
    with _client(workspace_root, providers or [_ready_provider()]) as c:
        response = c.get(READINESS)
    assert response.status_code == 200
    body: dict[str, object] = response.json()
    return body


@pytest.fixture(autouse=True)
def _prompts(workspace_root: Path) -> None:
    seed_prompts(workspace_root)


def test_readiness_404s_for_a_listing_that_was_never_saved(workspace_root: Path) -> None:
    with _client(workspace_root, [_ready_provider()]) as c:
        response = c.get("/api/listings/never-saved/ai-seo/readiness")

    assert response.status_code == 404


def test_readiness_is_ready_when_one_provider_is_ready(workspace_root: Path) -> None:
    providers: list[AiProvider] = [
        _unready_provider("codex", "not signed in"),
        _ready_provider("claude"),
    ]

    assert _readiness(workspace_root, providers) == {"ready": True, "reason": None}


@pytest.mark.parametrize("prompt", [SEO_PROMPT_FILE, MARKET_QUERIES_PROMPT_FILE])
def test_readiness_needs_both_prompts_the_run_reads(workspace_root: Path, prompt: str) -> None:
    (workspace_root / PROMPTS_DIR / prompt).unlink()

    body = _readiness(workspace_root)

    assert body["ready"] is False
    assert prompt in str(body["reason"])


def test_readiness_is_hidden_without_a_selected_design(workspace_root: Path) -> None:
    edit_listing(workspace_root, design={})

    body = _readiness(workspace_root)

    assert body["ready"] is False
    assert "design" in str(body["reason"])


def test_an_empty_brief_is_ready_because_the_button_drafts_it(workspace_root: Path) -> None:
    edit_listing(workspace_root, brief="   ")

    assert _readiness(workspace_root) == {"ready": True, "reason": None}


def test_an_empty_brief_needs_the_brief_prompt(workspace_root: Path) -> None:
    edit_listing(workspace_root, brief="")
    (workspace_root / PROMPTS_DIR / BRIEF_PROMPT_FILE).unlink()

    body = _readiness(workspace_root)

    assert body["ready"] is False
    assert BRIEF_PROMPT_FILE in str(body["reason"])


def test_readiness_is_hidden_without_a_usable_garment_profile(workspace_root: Path) -> None:
    edit_listing(workspace_root, garment_profile="no-such-profile")

    body = _readiness(workspace_root)

    assert body == {"ready": False, "reason": "the listing has no usable garment profile"}


def test_readiness_is_hidden_when_no_provider_is_ready(workspace_root: Path) -> None:
    providers: list[AiProvider] = [
        _unready_provider("codex", "codex is not authenticated"),
        _unready_provider("claude", "claude was not found on PATH"),
    ]

    body = _readiness(workspace_root, providers)

    assert body["ready"] is False
    assert "codex is not authenticated" in str(body["reason"])
    assert "claude was not found on PATH" in str(body["reason"])
