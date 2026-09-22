"""``ui/api/seo.py``'s HTTP surface (AI SEO implementation plan, PR5):
payload shape, status codes and the settled behaviours the plan's PR5
section names outright -- saved-only access, hidden readiness, concurrent
listing behaviour, provider-failure mapping, and no-write behaviour.

Every test drives `create_app` with a ``seo_provider_factory`` -- the same
injection seam `context_factory` already is for `ui/runs` -- wired to
`FakeSeoProvider` doubles or small local test doubles, never a real Codex or
Claude adapter (PR4's own rule: CI stays fake-provider-only).

Cancellation itself (the disconnect-to-`threading.Event` wiring) is unit
tested directly in `tests/unit/test_ai_seo_service.py` against
`generate_with_cancellation`, not here -- there is no way to make an
in-process ASGI transport simulate a genuinely dropped connection, and that
file's own docstring explains the seam split.
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

from etsy_listings.ai.models import ProviderReadiness, RawProviderResult, SeoRequest
from etsy_listings.ai.providers import FakeSeoProvider, SeoProvider
from etsy_listings.ui.api.app import create_app
from etsy_listings.workspace.layout import COMMON_COPY_DIR, PROMPTS_DIR, SEO_PROMPT_FILE
from etsy_listings.workspace.workspace import Workspace

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import copy_listing, edit_listing

_GARMENT_TITLE = "Unisex Garment-Dyed T-shirt"
"""`tests/fixtures/workspace/garment-profiles/comfort-colors-1717.yaml`'s
``blueprint.title`` -- the fixture value `_build_request`'s
``product_type`` fallback reads."""


def _valid_payload() -> str:
    return json.dumps(
        {
            "titles": ["Retro Sunset Hike Tee", "Take A Hike Graphic Shirt", "Mountain Trail Tee"],
            "tags": [f"tag{i}" for i in range(20)],
            "description_leads": ["lead one", "lead two", "lead three"],
            "rationale": [
                {
                    "phrase": f"phrase {i}",
                    "intent": "core_product",
                    "reason": "because",
                    "used_in": ["title"],
                }
                for i in range(7)
            ],
            "warnings": ["a non-blocking quality note"],
            "observed_text": "TAKE A HIKE",
        }
    )


def _seed_prompt(workspace_root: Path) -> Path:
    path = workspace_root / PROMPTS_DIR / SEO_PROMPT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Write great Etsy SEO copy.\n", encoding="utf-8")
    return path


def _ready_provider(name: str = "codex", *, responses: list[str] | None = None) -> FakeSeoProvider:
    return FakeSeoProvider(
        name=name,
        ready=ProviderReadiness(ready=True),
        responses=responses if responses is not None else [_valid_payload()],
    )


def _unready_provider(name: str, reason: str) -> FakeSeoProvider:
    return FakeSeoProvider(name=name, ready=ProviderReadiness(ready=False, reason=reason))


@contextmanager
def _client(
    workspace_root: Path, *, providers: list[SeoProvider] | None = None
) -> Iterator[TestClient]:
    workspace = Workspace.discover(root_override=workspace_root)
    kwargs: dict[str, Any] = {}
    if providers is not None:
        kwargs["seo_provider_factory"] = lambda _workspace: providers
    app = create_app(workspace, **kwargs)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def ready_provider() -> FakeSeoProvider:
    return _ready_provider()


@pytest.fixture
def client(workspace_root: Path, ready_provider: FakeSeoProvider) -> Iterator[TestClient]:
    """A client wired to one always-ready `FakeSeoProvider`, with
    ``prompts/seo.md`` already seeded -- the state every test starts from
    unless it is specifically testing a missing prerequisite."""
    _seed_prompt(workspace_root)
    with _client(workspace_root, providers=[ready_provider]) as test_client:
        yield test_client


# ------------------------------------------------------------------ readiness


def test_readiness_404s_for_a_listing_that_was_never_saved(client: TestClient) -> None:
    response = client.get("/api/listings/never-saved/ai-seo/readiness")

    assert response.status_code == 404


def test_readiness_is_hidden_without_prompts_seo_md(workspace_root: Path) -> None:
    with _client(workspace_root, providers=[_ready_provider()]) as c:
        response = c.get(f"/api/listings/{LISTING}/ai-seo/readiness")

        assert response.status_code == 200
        body = response.json()
        assert body["ready"] is False
        assert "seo.md" in body["reason"]


def test_readiness_is_hidden_without_a_selected_design(workspace_root: Path) -> None:
    _seed_prompt(workspace_root)
    edit_listing(workspace_root, design={})

    with _client(workspace_root, providers=[_ready_provider()]) as c:
        body = c.get(f"/api/listings/{LISTING}/ai-seo/readiness").json()

        assert body["ready"] is False
        assert "design" in body["reason"]


def test_readiness_is_hidden_with_an_empty_brief(workspace_root: Path) -> None:
    _seed_prompt(workspace_root)
    edit_listing(workspace_root, brief="   ")

    with _client(workspace_root, providers=[_ready_provider()]) as c:
        body = c.get(f"/api/listings/{LISTING}/ai-seo/readiness").json()

        assert body["ready"] is False
        assert "brief" in body["reason"]


def test_readiness_is_hidden_when_no_provider_is_ready(workspace_root: Path) -> None:
    _seed_prompt(workspace_root)
    providers = [
        _unready_provider("codex", "codex is not authenticated"),
        _unready_provider("claude", "claude was not found on PATH"),
    ]

    with _client(workspace_root, providers=providers) as c:
        body = c.get(f"/api/listings/{LISTING}/ai-seo/readiness").json()

        assert body["ready"] is False
        assert "codex is not authenticated" in body["reason"]
        assert "claude was not found on PATH" in body["reason"]


def test_readiness_is_ready_when_one_provider_is_ready(workspace_root: Path) -> None:
    _seed_prompt(workspace_root)
    providers = [_unready_provider("codex", "not signed in"), _ready_provider("claude")]

    with _client(workspace_root, providers=providers) as c:
        body = c.get(f"/api/listings/{LISTING}/ai-seo/readiness").json()

        assert body == {"ready": True, "reason": None}


# ------------------------------------------------------------------- proposal


def test_proposal_404s_for_a_listing_that_was_never_saved(client: TestClient) -> None:
    response = client.post("/api/listings/never-saved/ai-seo/proposal")

    assert response.status_code == 404


def test_proposal_409s_when_not_ready(workspace_root: Path) -> None:
    # No prompts/seo.md seeded.
    with _client(workspace_root, providers=[_ready_provider()]) as c:
        response = c.post(f"/api/listings/{LISTING}/ai-seo/proposal")

        assert response.status_code == 409
        assert "seo.md" in response.json()["detail"]


def test_proposal_returns_the_validated_payload_snapshot_and_expiry(client: TestClient) -> None:
    response = client.post(f"/api/listings/{LISTING}/ai-seo/proposal")

    assert response.status_code == 200
    body = response.json()

    assert body["titles"] == [
        "Retro Sunset Hike Tee",
        "Take A Hike Graphic Shirt",
        "Mountain Trail Tee",
    ]
    assert len(body["tags"]) == 20
    assert body["description_leads"] == ["lead one", "lead two", "lead three"]
    assert len(body["rationale"]) == 7
    assert body["rationale"][0] == {
        "phrase": "phrase 0",
        "intent": "core_product",
        "reason": "because",
        "used_in": ["title"],
    }
    assert body["warnings"] == [{"message": "a non-blocking quality note", "kind": "general"}]
    assert body["observed_text"] == "TAKE A HIKE"

    snapshot = body["snapshot"]
    assert snapshot["product_type"] == _GARMENT_TITLE
    assert snapshot["etsy_category"] == ""
    assert snapshot["materials"] == ["cotton"]
    assert snapshot["colors"] == ["black", "blue-jean", "ivory", "moss"]
    assert snapshot["garment_brand"] == "Comfort Colors"
    assert snapshot["garment_model"] == "1717"
    assert "Retro 70s sunset mountain scene" in snapshot["brief"]

    from datetime import datetime

    generated_at = datetime.fromisoformat(body["generated_at"])
    expires_at = datetime.fromisoformat(body["expires_at"])
    assert (expires_at - generated_at).total_seconds() == pytest.approx(86400, abs=1)


def test_proposal_surfaces_a_trademark_warning_from_hard_validation(
    workspace_root: Path,
) -> None:
    payload = json.loads(_valid_payload())
    payload["titles"][0] = "Nike-Inspired Take a Hike Tee"
    provider = _ready_provider(responses=[json.dumps(payload)])
    _seed_prompt(workspace_root)

    with _client(workspace_root, providers=[provider]) as c:
        body = c.post(f"/api/listings/{LISTING}/ai-seo/proposal").json()

    kinds = {w["kind"] for w in body["warnings"]}
    assert "trademark" in kinds


def test_proposal_502s_when_every_response_is_malformed(workspace_root: Path) -> None:
    provider = _ready_provider(responses=["not json", "still not json"])
    _seed_prompt(workspace_root)

    with _client(workspace_root, providers=[provider]) as c:
        response = c.post(f"/api/listings/{LISTING}/ai-seo/proposal")

    assert response.status_code == 502


def test_proposal_503s_when_every_provider_is_unavailable(workspace_root: Path) -> None:
    from etsy_listings.ai.errors import ProviderUnavailableError

    provider = _ready_provider()

    def _raise_unavailable(
        request: SeoRequest, deadline: Any, *, repair: Any = None, cancel_event: Any = None
    ) -> RawProviderResult:
        raise ProviderUnavailableError("codex", "not authenticated")

    provider.generate = _raise_unavailable  # type: ignore[method-assign]
    _seed_prompt(workspace_root)

    with _client(workspace_root, providers=[provider]) as c:
        response = c.post(f"/api/listings/{LISTING}/ai-seo/proposal")

    assert response.status_code == 503


def test_proposal_499s_when_generation_is_cancelled(workspace_root: Path) -> None:
    from etsy_listings.ai.errors import ProviderCancelledError

    provider = _ready_provider()

    def _raise_cancelled(
        request: SeoRequest, deadline: Any, *, repair: Any = None, cancel_event: Any = None
    ) -> RawProviderResult:
        raise ProviderCancelledError("codex")

    provider.generate = _raise_cancelled  # type: ignore[method-assign]
    _seed_prompt(workspace_root)

    with _client(workspace_root, providers=[provider]) as c:
        response = c.post(f"/api/listings/{LISTING}/ai-seo/proposal")

    assert response.status_code == 499


def test_proposal_502s_when_the_provider_process_cannot_even_start(
    workspace_root: Path,
) -> None:
    """`CliProcessError` (`ai/process.py.run_managed`'s own report that
    `subprocess.Popen` itself failed -- e.g. a binary readiness confirmed
    present and then removed before this call) is not a `SeoGenerationError`
    subclass, so it falls to `request_seo_proposal`'s catch-all rather than
    one of the named `except` clauses. Without that catch-all this would
    escape as FastAPI's unmapped, plain-text 500 instead of the "Try again"
    outcome the settled "Timeout and retries" decision promises for every
    failure that is not a recognised availability failure or a
    cancellation."""
    from etsy_listings.ai.process import CliProcessError

    provider = _ready_provider()

    def _raise_cli_process_error(
        request: SeoRequest, deadline: Any, *, repair: Any = None, cancel_event: Any = None
    ) -> RawProviderResult:
        raise CliProcessError("could not start ['codex', 'exec']: [WinError 2]")

    provider.generate = _raise_cli_process_error  # type: ignore[method-assign]
    _seed_prompt(workspace_root)

    with _client(workspace_root, providers=[provider]) as c:
        response = c.post(f"/api/listings/{LISTING}/ai-seo/proposal")

    assert response.status_code == 502
    assert "could not start" in response.json()["detail"]


def test_proposal_502s_with_the_usual_json_shape_for_any_unrecognised_adapter_bug(
    workspace_root: Path,
) -> None:
    """The catch-all in `request_seo_proposal` exists for exactly this case:
    an adapter bug this module cannot enumerate in advance (not a
    `SeoGenerationError` subclass at all, unlike every other error test in
    this file). It must still come back as this module's own
    ``{"detail": ...}`` JSON convention -- the same shape every other status
    code here uses -- rather than FastAPI's plain-text "Internal Server
    Error", which a future frontend (PR7) would have to special-case."""
    provider = _ready_provider()

    def _raise_unexpected(
        request: SeoRequest, deadline: Any, *, repair: Any = None, cancel_event: Any = None
    ) -> RawProviderResult:
        raise ZeroDivisionError("division by zero")

    provider.generate = _raise_unexpected  # type: ignore[method-assign]
    _seed_prompt(workspace_root)

    with _client(workspace_root, providers=[provider]) as c:
        response = c.post(f"/api/listings/{LISTING}/ai-seo/proposal")

    assert response.status_code == 502
    assert response.json() == {"detail": "division by zero"}


def test_proposal_frees_the_listing_after_an_unrecognised_adapter_bug(
    workspace_root: Path,
) -> None:
    """The catch-all must not bypass the ``finally`` -- an adapter bug on one
    request must not permanently strand the listing's
    :class:`~etsy_listings.ui.api.seo.ActiveSeoRequests` claim, the same
    property :func:`test_a_failed_request_still_frees_the_listing` proves
    for the named `SeoGenerationError` outcomes."""
    provider = _ready_provider(responses=[_valid_payload()])
    original_generate = provider.generate
    calls = {"count": 0}

    def _flaky_once(
        request: SeoRequest, deadline: Any, *, repair: Any = None, cancel_event: Any = None
    ) -> RawProviderResult:
        calls["count"] += 1
        if calls["count"] == 1:
            raise ZeroDivisionError("division by zero")
        return original_generate(request, deadline, repair=repair, cancel_event=cancel_event)

    provider.generate = _flaky_once  # type: ignore[method-assign]
    _seed_prompt(workspace_root)

    with _client(workspace_root, providers=[provider]) as c:
        failed = c.post(f"/api/listings/{LISTING}/ai-seo/proposal")
        assert failed.status_code == 502

        retried = c.post(f"/api/listings/{LISTING}/ai-seo/proposal")

    assert retried.status_code == 200


def test_proposal_409s_for_a_listing_with_no_usable_garment_profile(
    workspace_root: Path,
) -> None:
    _seed_prompt(workspace_root)
    edit_listing(workspace_root, garment_profile="does-not-exist")

    with _client(workspace_root, providers=[_ready_provider()]) as c:
        response = c.post(f"/api/listings/{LISTING}/ai-seo/proposal")

    assert response.status_code == 409
    assert "garment profile" in response.json()["detail"]


def test_proposal_leaves_the_workspace_unwritten(workspace_root: Path) -> None:
    _seed_prompt(workspace_root)
    listing_path = workspace_root / "listings" / LISTING / "listing.yaml"
    before_bytes = listing_path.read_bytes()
    before_tree = sorted(p.relative_to(workspace_root) for p in workspace_root.rglob("*"))

    with _client(workspace_root, providers=[_ready_provider()]) as c:
        response = c.post(f"/api/listings/{LISTING}/ai-seo/proposal")

    assert response.status_code == 200
    assert listing_path.read_bytes() == before_bytes
    after_tree = sorted(p.relative_to(workspace_root) for p in workspace_root.rglob("*"))
    assert after_tree == before_tree
    assert not (workspace_root / "listings" / LISTING / "state.lock.json").exists()
    assert not (workspace_root / COMMON_COPY_DIR / "ai-seo").exists()


# --------------------------------------------------------------- concurrency


@dataclass
class _BlockingProvider:
    """Blocks inside `generate()` until released -- so a test can prove a
    request is genuinely in flight (`started` fires) before deciding what a
    second, overlapping request sees."""

    ready: ProviderReadiness = field(default_factory=lambda: ProviderReadiness(ready=True))
    started: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)

    def readiness(self) -> ProviderReadiness:
        return self.ready

    def generate(
        self,
        request: SeoRequest,
        deadline: Any,
        *,
        repair: Any = None,
        cancel_event: Any = None,
    ) -> RawProviderResult:
        self.started.set()
        self.release.wait(timeout=10)
        return RawProviderResult(provider="codex", raw_output=_valid_payload())


@dataclass
class _ConcurrencyProbeProvider:
    """Records the highest number of ``generate()`` calls it ever saw in
    flight at once, then blocks every call on one shared ``release`` gate --
    proof that two overlapping requests were never serialised through this
    provider, whatever :class:`~etsy_listings.ui.api.seo.ActiveSeoRequests`
    otherwise refuses."""

    ready: ProviderReadiness = field(default_factory=lambda: ProviderReadiness(ready=True))
    release: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    concurrent_calls: int = field(default=0, init=False)
    max_concurrent: int = field(default=0, init=False)

    def readiness(self) -> ProviderReadiness:
        return self.ready

    def generate(
        self,
        request: SeoRequest,
        deadline: Any,
        *,
        repair: Any = None,
        cancel_event: Any = None,
    ) -> RawProviderResult:
        with self._lock:
            self.concurrent_calls += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent_calls)
        self.release.wait(timeout=10)
        with self._lock:
            self.concurrent_calls -= 1
        return RawProviderResult(provider="codex", raw_output=_valid_payload())


def test_a_second_request_for_the_same_listing_is_refused_while_the_first_is_active(
    workspace_root: Path,
) -> None:
    _seed_prompt(workspace_root)
    provider = _BlockingProvider()

    results: dict[str, int] = {}
    with _client(workspace_root, providers=[provider]) as c:
        thread = threading.Thread(
            target=lambda: results.__setitem__(
                "first", c.post(f"/api/listings/{LISTING}/ai-seo/proposal").status_code
            )
        )
        thread.start()
        assert provider.started.wait(timeout=5)

        second_response = c.post(f"/api/listings/{LISTING}/ai-seo/proposal")

        provider.release.set()
        thread.join(timeout=10)

    assert second_response.status_code == 409
    assert "already running" in second_response.json()["detail"]
    assert results["first"] == 200


def test_different_listings_run_concurrently(workspace_root: Path) -> None:
    _seed_prompt(workspace_root)
    copy_listing(workspace_root, "second-listing")
    provider = _ConcurrencyProbeProvider()

    results: dict[str, int] = {}
    with _client(workspace_root, providers=[provider]) as c:
        first = threading.Thread(
            target=lambda: results.__setitem__(
                "first", c.post(f"/api/listings/{LISTING}/ai-seo/proposal").status_code
            )
        )
        second = threading.Thread(
            target=lambda: results.__setitem__(
                "second",
                c.post("/api/listings/second-listing/ai-seo/proposal").status_code,
            )
        )
        first.start()
        second.start()

        deadline = time.monotonic() + 5
        while provider.max_concurrent < 2 and time.monotonic() < deadline:
            time.sleep(0.01)

        provider.release.set()
        first.join(timeout=10)
        second.join(timeout=10)

    assert provider.max_concurrent == 2
    assert results["first"] == 200
    assert results["second"] == 200


def test_ending_a_request_frees_the_listing_for_a_later_request(workspace_root: Path) -> None:
    """Not a concurrency test: proves the registry entry is released after a
    request finishes, so a *later*, non-overlapping request for the same
    listing is never permanently locked out by an earlier one."""
    _seed_prompt(workspace_root)
    provider = _ready_provider(responses=[_valid_payload(), _valid_payload()])

    with _client(workspace_root, providers=[provider]) as c:
        first = c.post(f"/api/listings/{LISTING}/ai-seo/proposal")
        second = c.post(f"/api/listings/{LISTING}/ai-seo/proposal")

    assert first.status_code == 200
    assert second.status_code == 200


def test_a_failed_request_still_frees_the_listing(workspace_root: Path) -> None:
    """A provider failure must release the active-request claim in its
    ``finally`` -- otherwise one failed generation would strand a listing
    refusing every later request forever."""
    provider = _ready_provider(responses=["not json", "still not json"])
    _seed_prompt(workspace_root)

    with _client(workspace_root, providers=[provider]) as c:
        failed = c.post(f"/api/listings/{LISTING}/ai-seo/proposal")
        assert failed.status_code == 502

        provider.responses = [_valid_payload()]
        retried = c.post(f"/api/listings/{LISTING}/ai-seo/proposal")

    assert retried.status_code == 200
