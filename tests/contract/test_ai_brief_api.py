"""``POST /api/listings/{name}/ai-seo/brief`` (PRD 68): payload shape, status
codes, and the two behaviours that make it safe for a caller nobody asked to
call -- it refuses rather than guesses when its prerequisites are missing,
and it never writes the drafted text anywhere.

Its own file rather than more of `test_ai_seo_api.py`: one test file, one
subject. That file's subject is the proposal surface -- readiness, the
proposal endpoint, staleness snapshots -- and half of what it establishes
(the seeded `prompts/seo.md`, a valid 20-tag payload, snapshot assertions)
has nothing to do with drafting a brief.

Cancellation is not retested here. Both endpoints go through one
`generate_with_cancellation`, unit tested directly in
`tests/unit/test_ai_seo_service.py`, for the reason that file's docstring
gives: an in-process ASGI transport cannot simulate a genuinely dropped
connection.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from etsy_listings.ai.models import Deadline, ProviderReadiness, ProviderTask, RawProviderResult
from etsy_listings.ai.providers import AiProvider, FakeAiProvider
from etsy_listings.ui.api.app import create_app
from etsy_listings.workspace.layout import BRIEF_PROMPT_FILE, PROMPTS_DIR
from etsy_listings.workspace.workspace import Workspace

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import edit_listing, listing_file

_DRAFT = "Retro sunset mountains. The design text reads exactly TAKE A HIKE."


def _payload(brief: str = _DRAFT) -> str:
    return json.dumps({"brief": brief})


def _seed_brief_prompt(workspace_root: Path) -> Path:
    path = workspace_root / PROMPTS_DIR / BRIEF_PROMPT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Describe the artwork.\n", encoding="utf-8")
    return path


def _ready_provider(name: str = "codex", *, responses: list[str] | None = None) -> FakeAiProvider:
    return FakeAiProvider(
        name=name,
        ready=ProviderReadiness(ready=True),
        responses=responses if responses is not None else [_payload()],
    )


@contextmanager
def _client(
    workspace_root: Path, *, providers: list[AiProvider] | None = None
) -> Iterator[TestClient]:
    workspace = Workspace.discover(root_override=workspace_root)
    kwargs: dict[str, Any] = {}
    if providers is not None:
        kwargs["seo_provider_factory"] = lambda _workspace: providers
    with TestClient(create_app(workspace, **kwargs)) as test_client:
        yield test_client


@pytest.fixture
def client(workspace_root: Path) -> Iterator[TestClient]:
    """The state a design attach leaves behind: a saved listing with a
    design, an empty brief, a seeded `prompts/brief.md`, and one ready
    provider."""
    _seed_brief_prompt(workspace_root)
    edit_listing(workspace_root, brief="")
    with _client(workspace_root, providers=[_ready_provider()]) as test_client:
        yield test_client


def _post(client: TestClient) -> Any:
    return client.post(f"/api/listings/{LISTING}/ai-seo/brief")


# ------------------------------------------------------------------ the draft


def test_a_drafted_brief_comes_back_as_plain_text(client: TestClient) -> None:
    response = _post(client)

    assert response.status_code == 200
    assert response.json() == {"brief": _DRAFT}


def test_the_provider_is_handed_the_listings_design_image(workspace_root: Path) -> None:
    _seed_brief_prompt(workspace_root)
    provider = _ready_provider()

    with _client(workspace_root, providers=[provider]) as c:
        _post(c)

    (task,) = provider.tasks
    assert task.design_image.name == "take-a-hike.png"
    assert "Describe the artwork." in task.prompt_text


def test_nothing_is_written_to_the_listing(workspace_root: Path, client: TestClient) -> None:
    """The settled rule PRD 4 keeps even as PRD 68 amends it: the model
    never writes `listing.yaml`. The editor does, through ordinary autosave,
    once it has this response."""
    before = listing_file(workspace_root).read_text(encoding="utf-8")

    assert _post(client).status_code == 200

    assert listing_file(workspace_root).read_text(encoding="utf-8") == before


def test_a_listing_that_already_has_a_brief_is_still_drafted_for(
    workspace_root: Path,
) -> None:
    """Deliberately *not* refused here. Only the browser knows whether the
    seller has typed into the field since the request was armed, and
    refusing from a file autosave may not have reached yet would refuse the
    common case (`ui/api/seo.py.request_design_brief`)."""
    _seed_brief_prompt(workspace_root)
    edit_listing(workspace_root, brief="Something the seller wrote.")

    with _client(workspace_root, providers=[_ready_provider()]) as c:
        assert _post(c).status_code == 200


# ------------------------------------------------------------------- refusals


def test_404_for_a_listing_that_was_never_saved(client: TestClient) -> None:
    assert client.post("/api/listings/never-saved/ai-seo/brief").status_code == 404


def test_409_without_a_selected_design(workspace_root: Path) -> None:
    _seed_brief_prompt(workspace_root)
    edit_listing(workspace_root, design={})

    with _client(workspace_root, providers=[_ready_provider()]) as c:
        response = _post(c)

        assert response.status_code == 409
        assert "design" in response.json()["detail"]


def test_409_without_prompts_brief_md(workspace_root: Path) -> None:
    """A workspace that predates this feature has no `prompts/brief.md`. It
    can still use AI Mode by hand; only the automatic draft is unavailable,
    and it says which file to seed."""
    with _client(workspace_root, providers=[_ready_provider()]) as c:
        response = _post(c)

        assert response.status_code == 409
        assert BRIEF_PROMPT_FILE in response.json()["detail"]


def test_409_when_no_provider_is_ready(workspace_root: Path) -> None:
    _seed_brief_prompt(workspace_root)
    providers = [
        FakeAiProvider(name="codex", ready=ProviderReadiness(ready=False, reason="not signed in")),
        FakeAiProvider(name="claude", ready=ProviderReadiness(ready=False, reason="no PATH entry")),
    ]

    with _client(workspace_root, providers=providers) as c:
        response = _post(c)

        assert response.status_code == 409
        assert "not signed in" in response.json()["detail"]
        assert "no PATH entry" in response.json()["detail"]


def test_502_when_generation_fails(workspace_root: Path) -> None:
    """An unrepairable response is "Try again", the same mapping the
    proposal endpoint uses -- `ui/api/seo.py._generation_errors` owns it
    once for both."""
    _seed_brief_prompt(workspace_root)
    provider = _ready_provider(responses=[_payload(""), _payload("   ")])

    with _client(workspace_root, providers=[provider]) as c:
        assert _post(c).status_code == 502


# ------------------------------------------------------------- concurrency


@dataclass
class _BlockingProvider:
    """Holds `generate()` open until released, so a second request can be
    made while the first is genuinely in flight."""

    name: str = "codex"
    ready: ProviderReadiness = field(default_factory=lambda: ProviderReadiness(ready=True))
    started: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)

    def readiness(self) -> ProviderReadiness:
        return self.ready

    def generate(
        self,
        task: ProviderTask,
        deadline: Deadline,
        *,
        repair: Any = None,
        cancel_event: threading.Event | None = None,
    ) -> RawProviderResult:
        self.started.set()
        self.release.wait(timeout=10)
        return RawProviderResult(provider=self.name, raw_output=_payload())


def test_a_second_brief_request_for_the_same_listing_is_refused(
    workspace_root: Path,
) -> None:
    _seed_brief_prompt(workspace_root)
    provider = _BlockingProvider()
    statuses: list[int] = []

    with _client(workspace_root, providers=[provider]) as c:
        first = threading.Thread(target=lambda: statuses.append(_post(c).status_code))
        first.start()
        assert provider.started.wait(timeout=10)

        second = _post(c)

        provider.release.set()
        first.join(timeout=10)

    assert second.status_code == 409
    assert "already running" in second.json()["detail"]
    assert statuses == [200]


def test_a_brief_request_does_not_block_this_listings_proposal(
    workspace_root: Path,
) -> None:
    """The chain's whole shape depends on this: a drafted brief is what
    unblocks a proposal, so the two are never rivals for one listing's
    slot."""
    from etsy_listings.ui.api.seo import ActiveSeoRequests

    active = ActiveSeoRequests()

    assert active.begin("brief", LISTING) is True
    assert active.begin("proposal", LISTING) is True


def test_a_slow_brief_never_holds_up_another_listing(workspace_root: Path) -> None:
    from tests.support.builders import copy_listing

    _seed_brief_prompt(workspace_root)
    copy_listing(workspace_root, "second-listing")
    provider = _BlockingProvider()

    with _client(workspace_root, providers=[provider]) as c:
        slow = threading.Thread(target=lambda: _post(c))
        slow.start()
        assert provider.started.wait(timeout=10)

        # The other listing's request reaches the same blocking provider, so
        # it is "accepted and running", not "refused" -- which is the claim.
        started_at = time.monotonic()
        other = threading.Thread(target=lambda: c.post("/api/listings/second-listing/ai-seo/brief"))
        other.start()

        provider.release.set()
        slow.join(timeout=10)
        other.join(timeout=10)

    assert time.monotonic() - started_at < 10
