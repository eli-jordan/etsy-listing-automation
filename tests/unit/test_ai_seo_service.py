"""``ui/api/seo.py``'s own machinery, exercised directly rather than through
a `TestClient` round trip: :class:`ActiveSeoRequests` (the settled
"Concurrent requests" decision's in-memory tracker) and
:func:`generate_with_cancellation` (the settled "Cancellation" decision's
disconnect-to-`threading.Event` wiring).

Both are deliberately public, not module-private, exactly so a test can
drive them directly rather than faking a dropped TCP connection through an
in-process ASGI transport that was never built to simulate one --
`generate_with_cancellation`'s own docstring says why. `tests/contract/
test_ai_seo_api.py` covers the two HTTP endpoints themselves, including
concurrent-listing behaviour through a real `TestClient` and background
threads; this file is the one level below that, where disconnect handling
and the active-request registry can be asserted against with no server, no
threads racing a live socket, and no polling interval to wait out longer
than it has to be.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from etsy_listings.ai.errors import ProviderCancelledError
from etsy_listings.ai.models import (
    Deadline,
    GarmentContext,
    ProviderReadiness,
    ProviderTask,
    RawProviderResult,
    RepairContext,
    SeoRequest,
)
from etsy_listings.ai.orchestrator import generate_proposal
from etsy_listings.ai.providers import FakeAiProvider
from etsy_listings.ui.api.seo import (
    ActiveSeoRequests,
    default_ai_providers,
    generate_with_cancellation,
)
from etsy_listings.workspace.workspace import Workspace

_PROMPT = "Write SEO copy."


def _seo_request() -> SeoRequest:
    return SeoRequest(
        brief="A retro sunset tee.",
        product_type="t-shirt",
        etsy_category="",
        materials=("cotton",),
        colors=("navy",),
        garment=GarmentContext(brand="Comfort Colors", model="1717"),
        design_image=Path("designs/front.png"),
    )


def _valid_payload() -> str:
    return json.dumps(
        {
            "titles": ["a" * 10, "b" * 10, "c" * 10],
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
            "warnings": [],
            "observed_text": "",
        }
    )


async def _never_disconnected() -> bool:
    return False


def _generation(providers: list[object]):  # noqa: ANN001, ANN202 - test helper
    """The blocking call `generate_with_cancellation` now takes.

    It races a *call*, not a request and a provider list (PRD 68 gave it a
    second kind of generation to race), so a test supplies the same closure
    the endpoints do."""
    return lambda cancel: generate_proposal(
        _seo_request(),
        _PROMPT,
        providers,  # type: ignore[arg-type]
        cancel_event=cancel,
    )


def _run(coro):  # noqa: ANN001, ANN202 - test helper, inference is exact
    """Runs ``coro`` to completion, tolerating a running event loop already
    left on *this* thread by something that ran earlier in the same pytest
    process. A Playwright-driven browser test (anything under
    `tests/browser/`) uses Playwright's sync API, which bridges to its own
    asyncio driver loop via a greenlet that switches back to the test thread
    without ever letting that loop's `run_forever()` frame return -- so
    `asyncio.get_running_loop()` (what bare `asyncio.run()` checks
    internally) keeps reporting a running loop on the main thread for the
    rest of the process, even though nothing is actually concurrently using
    it. A bare `asyncio.run(coro)` then raises `RuntimeError: asyncio.run()
    cannot be called from a running event loop` for every later test in this
    file, but only when a browser test file happened to run first in the
    same `pytest --cov` process -- this file passes in isolation and CI
    never reproduces it, since CI (and every other split invocation in this
    repo) runs browser and non-browser tests as separate processes.

    There is no existing sync-to-async bridge to reuse here:
    `ui/api/seo.py`'s own `generate_with_cancellation` never needs one --
    it runs as a coroutine already, inside the ASGI server's own loop -- and
    nothing else in this suite calls `asyncio.run(`. So this helper solves
    it directly: when this thread has no running loop, `asyncio.run` alone
    is correct and cheap. When it does (the Playwright leftover-state case,
    or true nested-loop misuse), run ``coro`` to completion on a *new*
    OS thread instead, where `asyncio.get_running_loop()` starts empty --
    sidestepping the ambient state entirely rather than trying to reuse or
    detect-and-ignore it.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: list[object] = []
    error: list[BaseException] = []

    def _target() -> None:
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread below
            error.append(exc)

    thread = threading.Thread(target=_target)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]


# --------------------------------------------------------- ActiveSeoRequests


def test_a_listing_can_only_be_claimed_once_at_a_time() -> None:
    active = ActiveSeoRequests()

    assert active.begin("proposal", "take-a-hike") is True
    assert active.begin("proposal", "take-a-hike") is False

    active.end("proposal", "take-a-hike")

    assert active.begin("proposal", "take-a-hike") is True


def test_different_listings_are_claimed_independently() -> None:
    active = ActiveSeoRequests()

    assert active.begin("proposal", "take-a-hike") is True
    assert active.begin("proposal", "another-listing") is True


def test_the_two_kinds_of_request_do_not_block_each_other() -> None:
    """A brief draft is what *unblocks* a proposal (PRD 68), so the two are
    never rivals -- refusing a proposal because a brief is in flight would
    break the automatic chain on its very first step."""
    active = ActiveSeoRequests()

    assert active.begin("brief", "take-a-hike") is True
    assert active.begin("proposal", "take-a-hike") is True


def test_ending_a_listing_that_was_never_begun_does_not_raise() -> None:
    ActiveSeoRequests().end("proposal", "never-claimed")


# ----------------------------------------------------- generate_with_cancellation


def test_returns_the_generated_proposal_when_never_disconnected() -> None:
    provider = FakeAiProvider(name="codex", responses=[_valid_payload()])

    proposal = _run(
        generate_with_cancellation(
            _generation([provider]),
            is_disconnected=_never_disconnected,
            poll_interval=0.01,
        )
    )

    assert proposal.titles[0] == "a" * 10
    assert provider.cancel_events[0] is not None
    assert provider.cancel_events[0].is_set() is False


@dataclass
class _CancelAwareProvider:
    """A `AiProvider` double that blocks inside `generate()` until its
    ``cancel_event`` is set, then raises `ProviderCancelledError` -- exactly
    the shape `ai/process.py.run_managed` and both real adapters already
    give a cancelled call (`ai/codex.py`, `ai/claude.py`: `if
    result.cancelled: raise ProviderCancelledError(...)`). `FakeAiProvider`
    itself never blocks, so it cannot stand in for "generation is still in
    flight when the disconnect happens" -- the one behaviour this test
    needs."""

    name: str = "codex"
    ready: ProviderReadiness = field(default_factory=lambda: ProviderReadiness(ready=True))
    started: threading.Event = field(default_factory=threading.Event)

    def readiness(self) -> ProviderReadiness:
        return self.ready

    def generate(
        self,
        task: ProviderTask,
        deadline: Deadline,
        *,
        repair: RepairContext | None = None,
        cancel_event: threading.Event | None = None,
    ) -> RawProviderResult:
        assert cancel_event is not None
        self.started.set()
        while not cancel_event.is_set():
            time.sleep(0.005)
        raise ProviderCancelledError(self.name)


def test_a_disconnect_sets_the_cancel_event_and_propagates_cancellation() -> None:
    provider = _CancelAwareProvider()
    disconnect_calls = 0

    async def is_disconnected() -> bool:
        nonlocal disconnect_calls
        disconnect_calls += 1
        # First poll: not yet. Second poll onward: the browser is gone.
        return disconnect_calls > 1

    async def scenario() -> None:
        try:
            await generate_with_cancellation(
                _generation([provider]),
                is_disconnected=is_disconnected,
                poll_interval=0.01,
            )
            raise AssertionError("expected ProviderCancelledError")
        except ProviderCancelledError:
            pass

    _run(scenario())

    assert provider.started.is_set()
    assert disconnect_calls >= 2


def test_never_disconnecting_never_touches_the_cancel_event() -> None:
    provider = FakeAiProvider(name="claude", responses=[_valid_payload()])

    _run(
        generate_with_cancellation(
            _generation([provider]),
            is_disconnected=_never_disconnected,
            poll_interval=0.01,
        )
    )

    recorded_event = provider.cancel_events[0]
    assert recorded_event is not None
    assert not recorded_event.is_set()


# --------------------------------------------------------- default_ai_providers


def test_default_ai_providers_is_codex_then_claude_over_the_workspace(
    workspace_root: Path,
) -> None:
    from etsy_listings.ai.claude import ClaudeProvider
    from etsy_listings.ai.codex import CodexProvider

    workspace = Workspace.discover(root_override=workspace_root)

    providers = default_ai_providers(workspace)

    assert [type(p) for p in providers] == [CodexProvider, ClaudeProvider]
    codex, claude = providers
    assert isinstance(codex, CodexProvider)
    assert isinstance(claude, ClaudeProvider)
    assert codex.workspace_root == workspace.root
    assert claude.workspace_root == workspace.root
