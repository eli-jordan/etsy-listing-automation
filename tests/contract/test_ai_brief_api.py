"""``POST /api/ai/design-brief`` (PRD 68): payload shape, status codes, and
the two behaviours that make it safe for a caller nobody asked to call -- it
refuses rather than guesses when its prerequisites are missing, and it never
writes the drafted text anywhere.

It is deliberately not a per-listing route. A seller creating a listing
attaches the design before naming it, and that is exactly when the brief is
wanted; a route under `/api/listings/{name}` could only answer 404 then. So
these tests never save a listing at all, which is itself the point.

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
from tests.support.builders import listing_file

_DRAFT = "Retro sunset mountains. The design text reads exactly TAKE A HIKE."
_DESIGN = f"designs/{LISTING}.png"
_PROFILE = "comfort-colors-1717"


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
    """The state a design pick leaves behind: a seeded `prompts/brief.md` and
    one ready provider. No listing is saved, named, or edited -- this endpoint
    never looks at one."""
    _seed_brief_prompt(workspace_root)
    with _client(workspace_root, providers=[_ready_provider()]) as test_client:
        yield test_client


def _post(client: TestClient, **over: str) -> Any:
    body = {"design": _DESIGN, "garment_profile": _PROFILE, **over}
    return client.post("/api/ai/design-brief", json=body)


# ------------------------------------------------------------------ the draft


def test_a_drafted_brief_comes_back_as_plain_text(client: TestClient) -> None:
    response = _post(client)

    assert response.status_code == 200
    assert response.json() == {"brief": _DRAFT}


def test_the_provider_is_handed_the_design_image_and_the_sellers_prompt(
    workspace_root: Path,
) -> None:
    _seed_brief_prompt(workspace_root)
    provider = _ready_provider()

    with _client(workspace_root, providers=[provider]) as c:
        _post(c)

    (task,) = provider.tasks
    assert task.design_image.name == f"{LISTING}.png"
    assert "Describe the artwork." in task.prompt_text


def test_nothing_is_written_to_the_workspace(workspace_root: Path, client: TestClient) -> None:
    """The settled rule PRD 4 keeps even as PRD 68 amends it: the model never
    writes `listing.yaml`. The editor does, through ordinary autosave, once it
    has this response."""
    before = listing_file(workspace_root).read_text(encoding="utf-8")
    tree = sorted(p.relative_to(workspace_root) for p in workspace_root.rglob("*"))

    assert _post(client).status_code == 200

    assert listing_file(workspace_root).read_text(encoding="utf-8") == before
    assert sorted(p.relative_to(workspace_root) for p in workspace_root.rglob("*")) == tree


# ------------------------------------------------------------------- refusals


def test_400_for_a_design_path_that_escapes_the_workspace(client: TestClient) -> None:
    """This value arrives from a browser, so `Workspace.resolve`'s boundary
    (`A8`) is a security check here, not a tidiness rule."""
    response = _post(client, design="../../../etc/passwd")

    assert response.status_code == 400


def test_409_for_a_design_that_does_not_exist(client: TestClient) -> None:
    response = _post(client, design="designs/nothing-here.png")

    assert response.status_code == 409
    assert "nothing-here" in response.json()["detail"]


def test_409_for_a_garment_profile_that_will_not_load(client: TestClient) -> None:
    response = _post(client, garment_profile="no-such-profile")

    assert response.status_code == 409
    assert "no-such-profile" in response.json()["detail"]


def test_409_without_prompts_brief_md(workspace_root: Path) -> None:
    """A workspace that predates this feature. AI Mode by hand still works;
    only the automatic draft is unavailable, and it says which file to seed."""
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
    """An unrepairable response is "Try again", the same mapping the proposal
    endpoint uses -- `ui/api/seo.py._generation_errors` owns it once for
    both."""
    _seed_brief_prompt(workspace_root)
    provider = _ready_provider(responses=[_payload(""), _payload("   ")])

    with _client(workspace_root, providers=[provider]) as c:
        assert _post(c).status_code == 502


# ------------------------------------------------------------- concurrency


@dataclass
class _BlockingProvider:
    """Holds `generate()` open until released, so a second request can be made
    while the first is genuinely in flight."""

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


def test_a_second_request_for_the_same_design_is_refused(workspace_root: Path) -> None:
    """Two editors drafting for one artwork would be two CLI subprocesses
    reading the same image to produce the same answer."""
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


def test_a_brief_request_does_not_block_a_listings_proposal(workspace_root: Path) -> None:
    """The chain's whole shape depends on this: a drafted brief is what
    unblocks a proposal, so the two are never rivals."""
    from etsy_listings.ui.api.seo import ActiveSeoRequests

    active = ActiveSeoRequests()

    assert active.begin("brief", _DESIGN) is True
    assert active.begin("proposal", LISTING) is True
