"""Browser test for the deploy view (docs/deploy-changes.md, PR (5)'s "done
when"): the one thing no other layer covers -- that the React app, the
FastAPI runs endpoints and the real engine agree about a whole plan -> apply
loop, streamed over SSE.

Runs against ``create_app(context_factory=fakes)``, following the same fake
`tests/contract/test_runs_api.py` and `tests/behaviour/test_runs_executor.py`
already established: the fixture workspace has no shop configured, so
`printify_product`/`publish`/`etsy_listing`/`etsy_media` all report
themselves blocked and only `render` actually does anything -- real local
file I/O, no network, which is what makes this test run with no credentials
and no Printify/Etsy sandbox.

The loop: open a listing, Deploy changes, watch the plan resolve with
previews, Apply, Back (which must never cancel an apply already under way),
*View progress* reattaches from the editor, the run finishes, and the
status pill reads what the server derives -- Deployed, not Live, since a
first apply only ever leaves an Etsy draft (non-goal 1).
"""

from __future__ import annotations

import shutil
import socket
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

from etsy_listings.clients.printify.fakes import FakeCatalogClient
from etsy_listings.engine.context import EventSink, RunContext
from etsy_listings.ui.api.app import FRONTEND_DIST, create_app
from etsy_listings.workspace.workspace import Workspace

pytestmark = pytest.mark.browser


def _context_factory(workspace: Workspace, on_event: EventSink | None) -> RunContext:
    kwargs = {"on_event": on_event} if on_event is not None else {}
    return RunContext(
        workspace=workspace,
        catalog=FakeCatalogClient([], {}, {}),
        printify=None,
        etsy=None,
        **kwargs,
    )


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@pytest.fixture
def deploy_server(workspace_root: Path, prerequisite_missing) -> Iterator[str]:  # noqa: ANN001
    """The real app, over `create_app(context_factory=fakes)` (this PR's own
    "done when"), against a throwaway copy of the fixture workspace -- so a
    run's writes (rendered PNGs, `state.lock.json`) land where this test can
    check them afterward."""
    if not FRONTEND_DIST.is_dir():
        prerequisite_missing(
            "ui/frontend/dist is absent -- run `npm run build` in "
            "src/etsy_listings/ui/frontend to exercise the browser tests"
        )

    workspace = Workspace.discover(root_override=workspace_root)
    port = _free_port()
    app = create_app(workspace, context_factory=_context_factory)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = threading.Event()
    for _ in range(30 * 20):
        if server.started:
            break
        deadline.wait(0.05)
    else:  # pragma: no cover - only on a pathologically slow machine
        server.should_exit = True
        pytest.fail("deploy server did not start in time")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


DEFAULT_TIMEOUT_MS = 60_000


@pytest.fixture
def page(browser_type, deploy_server: str):  # noqa: ANN001, ANN201
    context = browser_type.new_context(viewport={"width": 1280, "height": 960})
    context.set_default_timeout(DEFAULT_TIMEOUT_MS)
    context.set_default_navigation_timeout(DEFAULT_TIMEOUT_MS)
    page = context.new_page()
    page.goto(f"{deploy_server}/listings/take-a-hike")
    yield page
    context.close()


def test_deploy_plan_preview_apply_back_reattach_and_pill(
    page,  # noqa: ANN001
    workspace_root: Path,
) -> None:
    # -- Edit view: the new control, and nothing else about the page changed --
    page.get_by_role("heading", name="take-a-hike").wait_for(state="visible")
    page.get_by_role("button", name="Deploy changes →").click()

    # -- Deploy view: a real plan against the (fake-backed) engine --
    page.wait_for_url("**/listings/take-a-hike/deploy")
    page.get_by_role("heading", name="Deploy").wait_for(state="visible")

    # Every stage the plan touched shows up, whatever the fixture's missing
    # shop means for four of them -- the strip draws exactly what the plan
    # returned (decision 11), not a fixed five-stage assumption made here.
    page.get_by_text("Render mockups").wait_for(state="visible")
    page.get_by_text("Blocked").first.wait_for(state="visible")

    # Previews fill in: the render stage needed one per colour (the fixture's
    # scenes start unrendered), and Apply stays enabled only once they have
    # (decision 6). Waiting for the button itself to become enabled is the
    # observable effect of "previews finished" -- the internal `previewing`
    # phase is not something a browser test reaches into.
    apply_button = page.get_by_role("button", name="Apply")
    apply_button.wait_for(state="visible")
    for _ in range(200):
        if apply_button.is_enabled():
            break
        page.wait_for_timeout(100)
    else:
        raise AssertionError("Apply never became enabled once previews finished")

    # -- Apply, then Back immediately: it must never cancel the apply -- it
    # only leaves (decision 8). Whether this lands before or after the apply
    # itself finishes (a fixture this small can finish in milliseconds), the
    # invariant checked below is the one decision 8 actually makes: the run
    # ends applied, never cancelled.
    apply_button.click()
    page.get_by_role("button", name="← Back").click()

    page.wait_for_url("**/listings/take-a-hike")
    page.get_by_role("heading", name="take-a-hike").wait_for(state="visible")

    # -- Reattach: the page head offers a way back into whatever the run is
    # doing or has done, per decision 8's table -- accept either a still-in-
    # -progress or an already-finished label, since real timing decides which.
    reattach = page.locator(
        "button:has-text('View progress'), button:has-text('View result'), "
        "button:has-text('Deploy failed')"
    )
    reattach.first.wait_for(state="visible")
    reattach.first.click()

    page.wait_for_url("**/listings/take-a-hike/deploy")

    # -- The run finishes; the applied phase's own footer replaces Apply --
    page.get_by_text("Deployed.").wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
    page.get_by_role("button", name="← Back to editor").wait_for(state="visible")

    # `main` deliberately gives a just-finished apply 750 ms before marking
    # it seen, so an immediate first exit preserves View result. This is the
    # reattached result visit: let that grace period complete before leaving
    # and asserting the next editor view offers a fresh deploy.
    page.wait_for_timeout(800)

    # Observable effect, not internal state (CLAUDE.md's testing rule): the
    # render stage's own output is what "applied" actually did.
    rendered = workspace_root / ".cache" / "renders" / "take-a-hike" / "flat-lay-01" / "black.png"
    assert rendered.is_file()

    # -- Back to the editor: the pill is re-derived from the server, not
    # assumed by the page (decision 10) -- a first deploy reads Deployed,
    # never Live, since activating a listing is never this tool's to do
    # (non-goal 1).
    page.get_by_role("button", name="← Back to editor").click()
    page.wait_for_url("**/listings/take-a-hike")
    page.get_by_text("Deployed", exact=True).wait_for(state="visible")

    # And the page head is back to offering a fresh deploy -- the run just
    # shown was marked seen the moment its result rendered (decision 9).
    page.get_by_role("button", name="Deploy changes →").wait_for(state="visible")


def test_batch_apply_leaves_reattaches_and_continues_after_stale_listing(
    page,  # noqa: ANN001
    workspace_root: Path,
) -> None:
    """The workspace route preserves review while one listing goes stale.

    This deliberately changes one listing after its review and before Apply.
    That exercises the public A31 fingerprint guard and the sequential
    continue-on-error contract through the browser, rather than mocking either
    the API response or the React event stream.
    """
    second = workspace_root / "listings" / "second-shirt"
    shutil.copytree(workspace_root / "listings" / "take-a-hike", second)

    page.goto(page.url.rsplit("/listings/", 1)[0] + "/listings")
    page.get_by_role("button", name="Deploy changes: 2 to add").click()
    page.wait_for_url("**/listings/deploy/**")
    page.get_by_role("heading", name="Review all changes").wait_for(state="visible")

    apply_button = page.get_by_role("button", name="Apply")
    apply_button.wait_for(state="visible")
    for _ in range(200):
        if apply_button.is_enabled():
            break
        page.wait_for_timeout(100)
    else:
        raise AssertionError("batch Apply never became enabled once previews finished")

    listing_file = second / "listing.yaml"
    listing_file.write_text(
        listing_file.read_text(encoding="utf-8").replace(
            "Retro 70s sunset mountain scene.", "Changed after review."
        ),
        encoding="utf-8",
    )

    apply_button.click()
    page.get_by_role("button", name="← Back to listings").click()
    page.wait_for_url("**/listings")

    reattach = page.locator(
        "button:has-text('View batch progress'), button:has-text('View batch result')"
    )
    reattach.first.wait_for(state="visible")
    reattach.first.click()
    page.wait_for_url("**/listings/deploy/**")

    page.get_by_text("Batch partially applied.").wait_for(state="visible")
    page.get_by_text("1 listing succeeded · 1 listing stale").wait_for(state="visible")
    page.get_by_role("button", name="Plan again").wait_for(state="visible")
