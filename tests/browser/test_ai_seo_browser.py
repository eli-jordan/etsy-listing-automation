"""Browser test for Listing Details **AI Mode** (AI SEO implementation plan,
PR8): the one thing no other layer covers -- that the React drawers, the
FastAPI readiness/proposal endpoints, `ai/orchestrator.py`'s fallback and
repair logic, browser `localStorage` persistence, and (for the last test) the
real Printify desired-document builder all agree, end to end, in a real
browser against a real running app.

Every test drives ``create_app(seo_provider_factory=...)`` -- PR5's own
injection seam -- with `FakeSeoProvider` doubles (`ai/providers.py`, PR3) or
small local test doubles, exactly the way `tests/contract/test_ai_seo_api.py`
already does for the HTTP layer alone. No test here ever shells out to a real
Codex or Claude CLI (PR4's own rule: CI stays fake-provider-only).

Each test builds its own server (mirroring `test_deploy_view.py`'s own
`deploy_server`/`page` fixtures rather than the shared `conftest.py` ones)
because the providers a test wires in are exactly what it is testing --
`calibrator_server` has no seam for that at all, and threading one through a
shared fixture used by every other browser test file would make every other
file's server carry AI Mode's constructor arguments for no reason.
"""

from __future__ import annotations

import re
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import uvicorn
import yaml
from playwright.sync_api import Page

from etsy_listings.ai.errors import ProviderCancelledError, ProviderUnavailableError
from etsy_listings.ai.models import Deadline, ProviderReadiness, RawProviderResult, SeoRequest
from etsy_listings.ai.providers import FakeSeoProvider, SeoProvider
from etsy_listings.clients.printify.fakes import FakeCatalogClient, FakePrintifyClient
from etsy_listings.clients.printify.models import (
    Blueprint,
    PrintAreaPlaceholder,
    PrintProvider,
    ProductExternal,
    Shop,
    Variant,
    VariantOptions,
    VariantSet,
)
from etsy_listings.config.description import compose_description
from etsy_listings.engine.context import EventSink, RunContext
from etsy_listings.ui.api.app import FRONTEND_DIST, create_app
from etsy_listings.workspace.layout import COMMON_COPY_DIR, PROMPTS_DIR, SEO_PROMPT_FILE
from etsy_listings.workspace.workspace import Workspace

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import edit_listing, set_shop_id, write_design

pytestmark = pytest.mark.browser

DEFAULT_TIMEOUT_MS = 60_000
"""Same headroom as `conftest.py`'s own `DEFAULT_TIMEOUT_MS` -- every wait
here sits behind the real render/orchestration pipeline, under `pytest --cov`."""


# --------------------------------------------------------------------------
# Payload builders
#
# Every payload below is deliberately independent of `ai/validation.py`'s own
# rules, written out by hand rather than generated from a shared constant, so
# a test failure here means the server actually disagreed with a plain
# worked example -- not that a shared fixture drifted with the code it is
# supposed to check.
# --------------------------------------------------------------------------


def _rationale(n: int) -> list[dict[str, Any]]:
    return [
        {
            "phrase": f"phrase {i}",
            "intent": "core_product",
            "reason": f"reason {i}",
            "used_in": ["title", "tags", "description_lead"],
        }
        for i in range(n)
    ]


def _payload(
    *,
    titles: list[str] | None = None,
    tags: list[str] | None = None,
    leads: list[str] | None = None,
    warnings: list[str] | None = None,
    observed_text: str = "TAKE A HIKE",
) -> dict[str, Any]:
    default_titles = ["Retro Sunset Hike Tee", "Take A Hike Graphic Shirt", "Mountain Trail Tee"]
    default_leads = ["Lead option one.", "Lead option two.", "Lead option three."]
    return {
        "titles": titles or default_titles,
        "tags": tags or [f"tag{i}" for i in range(20)],
        "description_leads": leads or default_leads,
        "rationale": _rationale(7),
        "warnings": warnings or [],
        "observed_text": observed_text,
    }


def _valid_json(**kwargs: Any) -> str:
    import json

    return json.dumps(_payload(**kwargs))


# --------------------------------------------------------------------------
# Workspace setup helpers
# --------------------------------------------------------------------------


def _seed_prompt(workspace_root: Path) -> Path:
    path = workspace_root / PROMPTS_DIR / SEO_PROMPT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Write great Etsy SEO copy.\n", encoding="utf-8")
    return path


def _listing_yaml(workspace_root: Path, name: str = LISTING) -> dict[str, Any]:
    return yaml.safe_load(
        (workspace_root / "listings" / name / "listing.yaml").read_text(encoding="utf-8")
    )


def _workspace_snapshot(workspace_root: Path) -> tuple[bytes, list[Path]]:
    """Everything item 3 ("no listing field, no lockfile, no remote state
    changes from generation itself") needs to compare before and after: the
    exact bytes of the listing this request describes, and the full set of
    paths under the workspace -- so a lockfile or a stray `ai-seo` cache
    directory appearing would fail the comparison even though it is not
    `listing.yaml` itself.
    """
    listing_bytes = (workspace_root / "listings" / LISTING / "listing.yaml").read_bytes()
    tree = sorted(p.relative_to(workspace_root) for p in workspace_root.rglob("*"))
    return listing_bytes, tree


def _ready_provider(name: str = "codex", *, responses: list[str] | None = None) -> FakeSeoProvider:
    return FakeSeoProvider(
        name=name,
        ready=ProviderReadiness(ready=True),
        responses=responses if responses is not None else [_valid_json()],
    )


def _unready_provider(name: str, reason: str) -> FakeSeoProvider:
    return FakeSeoProvider(name=name, ready=ProviderReadiness(ready=False, reason=reason))


@dataclass
class _AlwaysUnavailableProvider:
    """A provider whose `readiness()` says it is fine, but whose `generate()`
    always raises a recognised-unavailable failure -- modelling a CLI whose
    sign-in expired *between* the cheap readiness probe and the real call, the
    one case the settled "Timeout and retries" decision permits to fall
    through to the next provider."""

    name: str = "codex"
    reason: str = "codex session expired mid-request"
    calls: int = field(default=0, init=False)

    def readiness(self) -> ProviderReadiness:
        return ProviderReadiness(ready=True)

    def generate(
        self,
        request: SeoRequest,
        deadline: Deadline,
        *,
        repair: Any = None,
        cancel_event: threading.Event | None = None,
    ) -> RawProviderResult:
        self.calls += 1
        raise ProviderUnavailableError(self.name, self.reason)


@dataclass
class _CancelAwareProvider:
    """Blocks inside `generate()` until `cancel_event` is set, then raises
    `ProviderCancelledError` -- exactly how a real adapter behaves once
    `ai/process.py.run_managed` kills its subprocess tree (PR4 item 5), so a
    browser test can prove the *whole* cancellation path (abort the fetch,
    detect the disconnect, set the event, stop the provider, retain nothing)
    without a fixed sleep standing in for the real signal.

    ``started`` lets a test wait until the request has actually reached this
    provider before it acts on it -- otherwise "click Cancel" could race
    "the POST has not even landed yet"."""

    name: str = "codex"
    started: threading.Event = field(default_factory=threading.Event)

    def readiness(self) -> ProviderReadiness:
        return ProviderReadiness(ready=True)

    def generate(
        self,
        request: SeoRequest,
        deadline: Deadline,
        *,
        repair: Any = None,
        cancel_event: threading.Event | None = None,
    ) -> RawProviderResult:
        self.started.set()
        assert cancel_event is not None, "the orchestrator must forward cancel_event"
        cancelled = cancel_event.wait(timeout=10)
        if not cancelled:
            raise AssertionError("cancel_event was never set -- the disconnect was not detected")
        raise ProviderCancelledError(self.name)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@contextmanager
def _seo_server(
    workspace_root: Path,
    prerequisite_missing: Any,
    *,
    providers: list[SeoProvider],
    context_factory: Any = None,
) -> Iterator[str]:
    """The real app -- built SPA served by FastAPI, exactly as `etsy-listings
    ui` runs it -- over `create_app(seo_provider_factory=...)`, so a test
    drives AI Mode's readiness and proposal endpoints against `FakeSeoProvider`
    doubles instead of a real Codex or Claude CLI."""
    if not FRONTEND_DIST.is_dir():
        prerequisite_missing(
            "ui/frontend/dist is absent -- run `npm run build` in "
            "src/etsy_listings/ui/frontend to exercise the browser tests"
        )

    workspace = Workspace.discover(root_override=workspace_root)
    port = _free_port()
    kwargs: dict[str, Any] = {"seo_provider_factory": lambda _workspace: providers}
    if context_factory is not None:
        kwargs["context_factory"] = context_factory
    app = create_app(workspace, **kwargs)
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
        pytest.fail("ai-seo server did not start in time")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@contextmanager
def _seo_page(
    browser_type: Any, base_url: str, path: str = f"/listings/{LISTING}"
) -> Iterator[Page]:
    context = browser_type.new_context(viewport={"width": 1280, "height": 1000})
    context.set_default_timeout(DEFAULT_TIMEOUT_MS)
    context.set_default_navigation_timeout(DEFAULT_TIMEOUT_MS)
    page = context.new_page()
    page.goto(f"{base_url}{path}")
    yield page
    context.close()


def _open_details_tab(page: Page) -> None:
    """`DetailsTab` -- and with it `useAiSeoMode` -- only mounts once the
    seller has actually switched to the **Listing Details** tab; the editor
    opens on a different tab by default (`test_listings_browser.py`'s own
    `.tabs .seg-opt` pattern)."""
    page.locator(".tabs .seg-opt", has_text="Listing Details").click()
    page.locator("#details-title").wait_for(state="visible")


def _wait_for_apply_enabled(page: Page) -> None:
    apply_button = page.get_by_role("button", name="Apply")
    apply_button.wait_for(state="visible")
    for _ in range(200):
        if apply_button.is_enabled():
            return
        page.wait_for_timeout(100)
    raise AssertionError("Apply never became enabled once previews finished")


# ===========================================================================
# 1. Independent title / tags / lead acceptance, and item 3's no-mutation
#    guarantee -- proven through the real browser+backend stack, which is a
#    stronger guarantee than the unit/API layers PR3/PR5 already covered
#    (implementation plan, PR8 item 3's own docstring reasoning).
# ===========================================================================


def test_full_workflow_independent_title_tags_and_lead_acceptance(
    browser_type: Any, workspace_root: Path, prerequisite_missing: Any
) -> None:
    _seed_prompt(workspace_root)
    provider = _ready_provider(
        responses=[
            _valid_json(
                titles=["Retro Sunset Hike Tee", "Take A Hike Graphic Shirt", "Mountain Trail Tee"],
                tags=[f"tag{i}" for i in range(20)],
                leads=["Lead option one.", "Lead option two.", "Lead option three."],
                warnings=["a non-blocking quality note"],
            )
        ]
    )

    with (
        _seo_server(workspace_root, prerequisite_missing, providers=[provider]) as base_url,
        _seo_page(browser_type, base_url) as page,
    ):
        page.get_by_role("heading", name=LISTING).wait_for(state="visible")
        _open_details_tab(page)
        ai_mode = page.get_by_role("button", name="AI Mode")
        ai_mode.wait_for(state="visible")

        before_bytes, before_tree = _workspace_snapshot(workspace_root)

        ai_mode.click()
        # The fake provider answers in-process, fast enough that the
        # loading state can come and go inside one Playwright poll --
        # `test_cancellation_...` below is what actually exercises it,
        # against a provider that blocks on purpose. What matters here is
        # what the interaction contract promises next: automatic reveal.
        title_drawer = page.get_by_role("region", name="title AI suggestions")
        title_drawer.wait_for(state="visible")
        tags_drawer = page.get_by_role("region", name="tag AI suggestions")
        tags_drawer.wait_for(state="visible")
        lead_drawer = page.get_by_role("region", name="description lead AI suggestions")
        lead_drawer.wait_for(state="visible")

        # -- Item 3: generation itself changed nothing yet --
        after_bytes, after_tree = _workspace_snapshot(workspace_root)
        assert after_bytes == before_bytes
        assert after_tree == before_tree
        assert not (workspace_root / "listings" / LISTING / "state.lock.json").exists()

        # -- Accessibility (section 10): focus lands in the first drawer --
        focused_region = page.evaluate(
            "document.activeElement?.closest('[role=region]')?.getAttribute('aria-label')"
        )
        assert focused_region == "title AI suggestions"

        # -- Disclosures: rationale/warnings/observed text are available,
        # not forced on the seller --
        title_drawer.get_by_text("Why these suggestions?").click()
        title_drawer.get_by_text("a non-blocking quality note").wait_for(state="visible")
        title_drawer.get_by_text("TAKE A HIKE", exact=True).wait_for(state="visible")

        # -- Title: one click both decides and applies, closes only its
        # drawer --
        title_drawer.get_by_role("button", name="Retro Sunset Hike Tee").click()
        title_drawer.wait_for(state="hidden")
        tags_drawer.wait_for(state="visible")  # untouched by the title drawer closing
        assert page.locator("#details-title").input_value() == "Retro Sunset Hike Tee"

        # -- Tags: individual toggle, both directions --
        first_tag = tags_drawer.get_by_role("button", name="+ tag0", exact=True)
        first_tag.click()
        page.locator(".chips .chip", has_text="tag0").wait_for(state="visible")
        tags_drawer.get_by_role("button", name="✓ tag0", exact=True).wait_for(state="visible")
        tags_drawer.get_by_role("button", name="✓ tag0", exact=True).click()
        page.locator(".chips .chip", has_text="tag0").wait_for(state="hidden")
        tags_drawer.get_by_role("button", name="+ tag0", exact=True).wait_for(state="visible")

        # -- The 13-tag cap: select every "Best 13" suggestion, then prove
        # a "More options" one is disabled, then free a slot --
        for i in range(13):
            tags_drawer.get_by_role("button", name=f"+ tag{i}", exact=True).click()
        tags_drawer.get_by_text("13 of 13 tags selected").wait_for(state="visible")
        more_option = tags_drawer.get_by_role("button", name="+ tag13", exact=True)
        assert more_option.get_attribute("aria-disabled") == "true"
        more_option.click(force=True)
        page.locator(".chips .chip", has_text="tag13").wait_for(state="hidden")  # no-op

        tags_drawer.get_by_role("button", name="✓ tag0", exact=True).click()
        tags_drawer.get_by_text("12 of 13 tags selected").wait_for(state="visible")
        more_option = tags_drawer.get_by_role("button", name="+ tag13", exact=True)
        assert more_option.get_attribute("aria-disabled") == "false"
        more_option.click()
        page.locator(".chips .chip", has_text="tag13").wait_for(state="visible")
        tags_drawer.get_by_text("13 of 13 tags selected").wait_for(state="visible")

        # -- Accept best 13 replaces the whole collection wholesale,
        # regardless of the manual toggles just made, and closes the
        # drawer --
        tags_drawer.get_by_role("button", name="Accept best 13").click()
        tags_drawer.wait_for(state="hidden")
        chips = page.locator(".chips .chip")
        assert chips.count() == 13
        for i in range(13):
            assert chips.filter(has_text=re.compile(rf"^tag{i}\D*$")).count() == 1, i
        # `tag13` was individually toggled on above and then wholesale
        # replaced by Accept best 13 -- it must not survive.
        assert chips.filter(has_text=re.compile(r"^tag13\D*$")).count() == 0

        # -- Lead: Reject all leaves the field untouched --
        lead_drawer.get_by_role("button", name="Reject all").click()
        lead_drawer.wait_for(state="hidden")
        assert page.locator("#details-description-lead").input_value() == ""

        # -- Every accepted value went through ordinary autosave: reload
        # and confirm it is really on disk, not only in React state --
        page.wait_for_timeout(500)  # autosave's own debounce
        for _ in range(50):
            written = _listing_yaml(workspace_root)
            if (
                written["etsy"]["title"] == "Retro Sunset Hike Tee"
                and len(written["etsy"]["tags"]) == 13
            ):
                break
            page.wait_for_timeout(100)
        else:
            raise AssertionError(f"autosave never wrote the accepted values: {written}")
        assert written["etsy"]["title"] == "Retro Sunset Hike Tee"
        assert sorted(written["etsy"]["tags"]) == sorted(f"tag{i}" for i in range(13))
        assert written["etsy"]["description"]["lead"] == ""  # rejected, untouched

        # -- Every drawer resolved: the pending proposal is gone, and so
        # is the AI Mode control's own busy state; the button is usable
        # again --
        remaining = page.evaluate(
            "prefix => Object.keys(localStorage).filter(k => k.startsWith(prefix))",
            "ai-seo-proposal:",
        )
        assert remaining == []
        ai_mode.wait_for(state="visible")
        assert ai_mode.is_enabled()


# ===========================================================================
# 2. AI Mode stays visible but disabled until its prerequisites are ready.
#    The brief test starts empty and fills it through the real editor; the
#    other two exercise provider and prompt readiness.
# ===========================================================================


def test_editing_an_empty_brief_enables_ai_mode_after_autosave(
    browser_type: Any, workspace_root: Path, prerequisite_missing: Any
) -> None:
    _seed_prompt(workspace_root)
    edit_listing(workspace_root, brief="")
    provider = _ready_provider()

    with (
        _seo_server(workspace_root, prerequisite_missing, providers=[provider]) as base_url,
        _seo_page(browser_type, base_url) as page,
    ):
        page.get_by_role("heading", name=LISTING).wait_for(state="visible")
        _open_details_tab(page)
        ai_mode = page.get_by_role("button", name="AI Mode")
        assert ai_mode.is_disabled()
        assert page.locator(".seo-brief-row").get_by_role("button", name="AI Mode").count() == 1
        page.locator(".seo-ai-mode-anchor").hover()
        tip = page.get_by_role("tooltip")
        tip.wait_for(state="visible")
        assert "Brief filled in" in tip.inner_text()
        fills = page.locator(".seo-ai-mode svg path").evaluate_all(
            "paths => paths.map(path => getComputedStyle(path).fill)"
        )
        assert fills == ["rgb(118, 85, 201)", "rgb(220, 94, 154)"]

        brief = page.get_by_role("textbox", name="Brief")
        assert brief.input_value() == ""
        brief.fill("A retro sunset tee that says TAKE A HIKE.")
        page.locator("#details-title").click()  # blur and flush the brief

        for _ in range(100):
            if (
                _listing_yaml(workspace_root)["brief"]
                == "A retro sunset tee that says TAKE A HIKE."
            ):
                break
            page.wait_for_timeout(100)
        else:
            raise AssertionError("brief edit never reached listing.yaml")

        # The first readiness request may have raced the write and seen the
        # old empty brief; the saved response must trigger another check.
        page.wait_for_function("document.querySelector('.seo-ai-mode')?.disabled === false")
        assert ai_mode.is_enabled()

        ai_mode.click()
        page.get_by_role("region", name="title AI suggestions").wait_for(state="visible")
        assert len(provider.requests) == 1
        assert provider.requests[0].brief == "A retro sunset tee that says TAKE A HIKE."


def test_ai_mode_is_disabled_when_no_provider_is_ready(
    browser_type: Any, workspace_root: Path, prerequisite_missing: Any
) -> None:
    _seed_prompt(workspace_root)
    providers: list[SeoProvider] = [
        _unready_provider("codex", "codex is not authenticated"),
        _unready_provider("claude", "claude was not found on PATH"),
    ]

    with (
        _seo_server(workspace_root, prerequisite_missing, providers=providers) as base_url,
        _seo_page(browser_type, base_url) as page,
    ):
        page.get_by_role("heading", name=LISTING).wait_for(state="visible")
        _open_details_tab(page)

        # The readiness endpoint explains why the visible control is disabled.
        readiness = page.request.get(f"{base_url}/api/listings/{LISTING}/ai-seo/readiness")
        body = readiness.json()
        assert body["ready"] is False
        assert "codex is not authenticated" in body["reason"]
        assert "claude was not found on PATH" in body["reason"]

        page.wait_for_timeout(500)  # let the readiness effect actually settle
        assert page.get_by_role("button", name="AI Mode").is_disabled()
        page.locator(".seo-ai-mode-anchor").hover()
        assert "no AI provider is ready" in page.get_by_role("tooltip").inner_text()


def test_ai_mode_is_disabled_without_prompts_seo_md(
    browser_type: Any, workspace_root: Path, prerequisite_missing: Any
) -> None:
    # Deliberately no `_seed_prompt` call -- `prompts/` does not even exist.
    provider = _ready_provider()

    with (
        _seo_server(workspace_root, prerequisite_missing, providers=[provider]) as base_url,
        _seo_page(browser_type, base_url) as page,
    ):
        page.get_by_role("heading", name=LISTING).wait_for(state="visible")
        _open_details_tab(page)

        readiness = page.request.get(f"{base_url}/api/listings/{LISTING}/ai-seo/readiness")
        body = readiness.json()
        assert body["ready"] is False
        assert "seo.md" in body["reason"]

        page.wait_for_timeout(500)
        assert page.get_by_role("button", name="AI Mode").is_disabled()
        # Nothing about the missing prompt file is this feature's to fix
        # on its own -- `setup` seeds it (implementation plan, "Prompt").
        assert not (workspace_root / PROMPTS_DIR / SEO_PROMPT_FILE).exists()


# ===========================================================================
# 3. Stale proposal: a submitted-input change keeps the proposal visible but
#    unselectable, and regenerating preserves whatever was already accepted
#    (implementation plan, "Proposal and stale-state rules"; PR7 item 4).
# ===========================================================================


def test_a_changed_editor_input_stales_unresolved_choices_until_regenerated(
    browser_type: Any, workspace_root: Path, prerequisite_missing: Any
) -> None:
    provider = _ready_provider(
        responses=[
            _valid_json(titles=["First Title Option", "Second Title Option", "Third Title Option"]),
            _valid_json(
                titles=["Fresh First Title", "Fresh Second Title", "Fresh Third Title"],
                tags=[f"newtag{i}" for i in range(20)],
                leads=["Fresh lead one.", "Fresh lead two.", "Fresh lead three."],
            ),
        ]
    )
    _seed_prompt(workspace_root)

    with (
        _seo_server(workspace_root, prerequisite_missing, providers=[provider]) as base_url,
        _seo_page(browser_type, base_url) as page,
    ):
        page.get_by_role("heading", name=LISTING).wait_for(state="visible")
        _open_details_tab(page)
        ai_mode = page.get_by_role("button", name="AI Mode")
        ai_mode.wait_for(state="visible")
        ai_mode.click()

        title_drawer = page.get_by_role("region", name="title AI suggestions")
        tags_drawer = page.get_by_role("region", name="tag AI suggestions")
        lead_drawer = page.get_by_role("region", name="description lead AI suggestions")
        title_drawer.wait_for(state="visible")
        tags_drawer.wait_for(state="visible")
        lead_drawer.wait_for(state="visible")

        # Accept the title before staling everything else -- once
        # accepted it is ordinary listing content and must not gain a
        # stale badge of its own (section 7: "no longer tied to the
        # proposal").
        title_drawer.get_by_role("button", name="First Title Option").click()
        title_drawer.wait_for(state="hidden")

        # A submitted generation input changes: the Section field feeds
        # `etsy_category` (`aiSeoStorage.ts.buildComparableSnapshot`).
        section = page.get_by_label("Section")
        section.fill("Trail Gear")
        page.locator("#details-title").click()  # blur Section, flush autosave

        tags_drawer.get_by_text("Suggestions are out of date").wait_for(state="visible")
        lead_drawer.get_by_text("Suggestions are out of date").wait_for(state="visible")

        # Stale suggestions cannot be selected: the choice buttons are
        # disabled, and a tag toggle is a no-op even if forced.
        assert lead_drawer.get_by_role("button", name="Lead option one.").is_disabled()
        first_more_tag = tags_drawer.get_by_role("button", name="+ tag14", exact=True)
        assert first_more_tag.get_attribute("aria-disabled") == "true"
        first_more_tag.click(force=True)
        page.locator(".chips .chip", has_text="tag14").wait_for(state="hidden")

        # Regenerate: the AI Mode control itself doubles as Regenerate
        # once a proposal is stale, and is not disabled by staleness
        # (only by an in-flight request).
        assert ai_mode.is_enabled()
        ai_mode.click()

        fresh_title_drawer = page.get_by_role("region", name="title AI suggestions")
        fresh_tags_drawer = page.get_by_role("region", name="tag AI suggestions")
        fresh_lead_drawer = page.get_by_role("region", name="description lead AI suggestions")
        fresh_lead_drawer.get_by_role("button", name="Fresh lead one.").wait_for(state="visible")
        fresh_tags_drawer.get_by_role("button", name="+ newtag0", exact=True).wait_for(
            state="visible"
        )
        # Fresh, not stale: the disabled treatment is gone.
        assert fresh_lead_drawer.get_by_role("button", name="Fresh lead one.").is_enabled()

        # A fresh proposal reopens every drawer, including title's --
        # but the value the seller already accepted is untouched until
        # they pick something new from it (implementation plan, section
        # 7: "Preserve all values already chosen into normal fields").
        fresh_title_drawer.get_by_role("button", name="Fresh First Title").wait_for(state="visible")
        assert page.locator("#details-title").input_value() == "First Title Option"


# ===========================================================================
# 4. Cancellation: the loading state exposes Cancel, aborting it retains no
#    proposal and changes no listing field, and the backend genuinely
#    terminates the in-flight generation rather than merely ignoring its
#    result (implementation plan, "Cancellation"; PR5 item 3).
# ===========================================================================


def test_cancel_during_generation_retains_no_proposal_and_frees_the_listing(
    browser_type: Any, workspace_root: Path, prerequisite_missing: Any
) -> None:
    _seed_prompt(workspace_root)
    provider = _CancelAwareProvider()
    providers: list[SeoProvider] = [provider]

    with (
        _seo_server(workspace_root, prerequisite_missing, providers=providers) as base_url,
        _seo_page(browser_type, base_url) as page,
    ):
        page.get_by_role("heading", name=LISTING).wait_for(state="visible")
        _open_details_tab(page)
        ai_mode = page.get_by_role("button", name="AI Mode")
        ai_mode.wait_for(state="visible")

        before_bytes, before_tree = _workspace_snapshot(workspace_root)

        ai_mode.click()
        page.get_by_text("Generating for", exact=False).wait_for(state="visible")
        assert ai_mode.is_disabled()
        cancel_button = page.get_by_role("button", name="Cancel")
        cancel_button.wait_for(state="visible")

        # Make sure the request genuinely reached the provider before
        # cancelling it -- otherwise this would only prove aborting an
        # already-finished request is harmless, not cancellation itself.
        assert provider.started.wait(timeout=10)
        cancel_button.click()

        # The loading state clears, no drawer ever appears, and nothing
        # about the listing changed -- not even a lockfile.
        page.get_by_text("Generating for", exact=False).wait_for(state="hidden")
        assert page.get_by_role("region", name="title AI suggestions").count() == 0
        assert page.get_by_role("region", name="tag AI suggestions").count() == 0
        assert page.get_by_role("region", name="description lead AI suggestions").count() == 0
        after_bytes, after_tree = _workspace_snapshot(workspace_root)
        assert after_bytes == before_bytes
        assert after_tree == before_tree

        # The backend actually cancelled the provider call (proved by
        # `_CancelAwareProvider.generate` itself: it only returns once
        # `cancel_event` was set, or raises `AssertionError` if it timed
        # out waiting) -- and released `ActiveSeoRequests`' claim on this
        # *same* listing, on this *same* running server, so a fresh
        # request works immediately rather than 409ing forever.
        assert ai_mode.is_enabled()
        providers[0] = _ready_provider()
        # The client returns to idle the moment it aborts its own fetch,
        # but the server's disconnect *detection* is a poll
        # (`_DISCONNECT_POLL_SECONDS` = 0.25s) -- give that a moment to
        # actually finish releasing `ActiveSeoRequests`' claim before
        # asking for a fresh request, or this would flakily race a 409 --
        # that race itself is `test_ai_seo_api.py`'s own
        # `test_a_second_request_for_the_same_listing_is_refused_while_the_first_is_active`,
        # not this test's job.
        page.wait_for_timeout(750)
        ai_mode.click()
        page.get_by_role("region", name="title AI suggestions").wait_for(state="visible")


# ===========================================================================
# 5. Malformed provider output: one same-provider repair attempt, and "Try
#    again" -- never a partial proposal -- once repair also fails
#    (implementation plan, "Validation"; PR3/PR4's repair contract).
# ===========================================================================


def test_malformed_output_is_repaired_once_then_try_again_recovers(
    browser_type: Any, workspace_root: Path, prerequisite_missing: Any
) -> None:
    _seed_prompt(workspace_root)
    provider = _ready_provider(responses=["not json at all", '{"still": "not a proposal"}'])
    providers: list[SeoProvider] = [provider]

    with (
        _seo_server(workspace_root, prerequisite_missing, providers=providers) as base_url,
        _seo_page(browser_type, base_url) as page,
    ):
        page.get_by_role("heading", name=LISTING).wait_for(state="visible")
        _open_details_tab(page)
        ai_mode = page.get_by_role("button", name="AI Mode")
        ai_mode.wait_for(state="visible")

        before_bytes, before_tree = _workspace_snapshot(workspace_root)
        ai_mode.click()

        # One repair attempt happened server-side (the second queued
        # response was consumed) and it was *also* malformed, so this
        # surfaces as "Try again" -- never a partial proposal.
        failure_text = "AI Mode couldn’t generate valid suggestions. Nothing changed."
        page.get_by_text(failure_text).wait_for(state="visible")
        assert len(provider.requests) == 2
        assert provider.repairs[0] is None
        assert provider.repairs[1] is not None
        assert page.get_by_role("region", name="title AI suggestions").count() == 0
        after_bytes, after_tree = _workspace_snapshot(workspace_root)
        assert after_bytes == before_bytes
        assert after_tree == before_tree

        # Try again, now with a valid response queued: recovers cleanly.
        provider.responses = [_valid_json()]
        page.get_by_role("button", name="Try again").click()
        page.get_by_role("region", name="title AI suggestions").wait_for(state="visible")


# ===========================================================================
# 6. Provider fallback: a recognised-unavailable failure from the first
#    provider falls through to the next one in the chain, within the same
#    request (implementation plan, "Timeout and retries"; PR4 item 3).
# ===========================================================================


def test_codex_unavailable_falls_through_to_claude(
    browser_type: Any, workspace_root: Path, prerequisite_missing: Any
) -> None:
    _seed_prompt(workspace_root)
    codex = _AlwaysUnavailableProvider(name="codex", reason="codex session expired mid-request")
    claude = _ready_provider(
        name="claude", responses=[_valid_json(titles=["Claude Wrote This One", "Second", "Third"])]
    )

    with (
        _seo_server(workspace_root, prerequisite_missing, providers=[codex, claude]) as base_url,
        _seo_page(browser_type, base_url) as page,
    ):
        page.get_by_role("heading", name=LISTING).wait_for(state="visible")
        _open_details_tab(page)
        ai_mode = page.get_by_role("button", name="AI Mode")
        ai_mode.wait_for(state="visible")  # both report ready() = True

        ai_mode.click()
        title_drawer = page.get_by_role("region", name="title AI suggestions")
        title_drawer.get_by_role("button", name="Claude Wrote This One").wait_for(state="visible")
        assert codex.calls == 1
        assert len(claude.requests) == 1


# ===========================================================================
# 7. Pending-proposal persistence: survives an ordinary refresh, and expires
#    after its one-day window, scoped to workspace and listing
#    (implementation plan, "Proposal persistence"; `aiSeoStorage.ts`).
# ===========================================================================


def _stored_proposal_key(page: Page) -> str:
    storage_id = page.evaluate(
        "async () => (await (await fetch('/api/workspace')).json()).storage_id"
    )
    keys = page.evaluate(
        "prefix => Object.keys(localStorage).filter(k => k.startsWith(prefix))",
        f"ai-seo-proposal:{storage_id}:{LISTING}",
    )
    assert len(keys) == 1, keys
    key: str = keys[0]
    return key


def test_pending_proposal_survives_refresh_and_expires_after_one_day(
    browser_type: Any, workspace_root: Path, prerequisite_missing: Any
) -> None:
    _seed_prompt(workspace_root)
    persisted_titles = ["Persisted Title One", "Persisted Title Two", "Persisted Title Three"]
    provider = _ready_provider(responses=[_valid_json(titles=persisted_titles)])

    with (
        _seo_server(workspace_root, prerequisite_missing, providers=[provider]) as base_url,
        _seo_page(browser_type, base_url) as page,
    ):
        page.get_by_role("heading", name=LISTING).wait_for(state="visible")
        _open_details_tab(page)
        page.get_by_role("button", name="AI Mode").click()
        title_drawer = page.get_by_role("region", name="title AI suggestions")
        title_drawer.get_by_role("button", name="Persisted Title One").wait_for(state="visible")

        # Scoped exactly by workspace identity and listing, per
        # `aiSeoStorage.ts.storageKey` -- not just "a" key.
        key = _stored_proposal_key(page)
        stored = page.evaluate("k => JSON.parse(localStorage.getItem(k))", key)
        assert stored["proposal"]["titles"][0] == "Persisted Title One"

        # -- An ordinary refresh restores the unresolved drawers in place,
        # with no second network request needed --
        page.reload()
        _open_details_tab(page)
        page.get_by_role("region", name="title AI suggestions").get_by_role(
            "button", name="Persisted Title One"
        ).wait_for(state="visible")
        assert len(provider.requests) == 1  # never asked again

        # -- Rewrite the same entry with an already-past expiry, exactly
        # the shape `aiSeoStorage.ts` itself writes, then reload:
        # `loadStoredProposal` discards an expired entry as a side effect
        # of the read (item 3: "discard expired ones"), so no drawer
        # reappears and the key itself is gone --
        stored["proposal"]["expires_at"] = "2000-01-01T00:00:00.000Z"
        page.evaluate("([k, v]) => localStorage.setItem(k, JSON.stringify(v))", [key, stored])
        page.reload()
        _open_details_tab(page)
        page.wait_for_timeout(500)
        assert page.get_by_role("region", name="title AI suggestions").count() == 0
        assert page.evaluate("k => localStorage.getItem(k)", key) is None


# ===========================================================================
# 8. Common-copy description composition, through a real deployment: PR6's
#    shared composer (`Workspace.compose_description`) resolves a
#    `common-copy/` reference identically wherever it is consumed
#    (implementation plan, "Description and common-copy boundaries") -- here
#    proved through the *actual* `printify_product` desired-document builder
#    (`engine/stages/printify_product.py`, PR2), driven by a real browser
#    click on Apply, not a direct call into that stage's own tests.
#
# AI Mode itself plays no part in this one; it is item 2's own last bullet,
# grouped with the rest of AI Mode's browser coverage because it exercises
# the other half of this PR8's mandate: the description model AI Mode's lead
# drawer writes into is the same one this composition reads out of.
# ===========================================================================

_PRINTIFY_BLUEPRINT = Blueprint(
    id=706, title="Unisex Garment-Dyed T-shirt", brand="Comfort Colors®", model="1717"
)
"""Matches `tests/fixtures/workspace/garment-profiles/comfort-colors-1717.yaml`'s
`blueprint.brand`/`model` (brand/model, not title, is the resolution key --
see that fixture's own comment) -- id and title are otherwise arbitrary
Printify-side facts, transcribed from `test_printify_product_stage.py` rather
than invented again, since both exist to describe the same fixture profile."""
_PRINTIFY_PROVIDER = PrintProvider(id=29, title="Monster Digital")
_PRINTIFY_COLOURS = ["Black", "Blue Jean", "Ivory", "Moss"]
_PRINTIFY_SIZES = ["S", "M", "L", "XL", "XXL", "XXXL"]
_PRINT_AREA = (4500, 5400)  # the garment profile's own `print_area`
_SHOP_ID = 28819281


def _printify_variants() -> VariantSet:
    placeholder = PrintAreaPlaceholder(
        position="front", width=_PRINT_AREA[0], height=_PRINT_AREA[1]
    )
    return VariantSet(
        variants=tuple(
            Variant(
                id=1000 + colour_index * 10 + size_index,
                title=f"{colour} / {size}",
                options=VariantOptions(color=colour, size=size),
                placeholders=(placeholder,),
            )
            for colour_index, colour in enumerate(_PRINTIFY_COLOURS)
            for size_index, size in enumerate(_PRINTIFY_SIZES)
        )
    )


_COMMON_COPY_BODY = (
    "Runs true to size in a relaxed, garment-dyed fit.\n\n"
    "Machine wash cold with like colours, tumble dry low."
)
_LEAD = "A relaxed heavyweight tee for the trail and the coffee stop after it."


def _write_common_copy(workspace_root: Path) -> None:
    path = workspace_root / COMMON_COPY_DIR / "comfort-colors.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "title: Comfort Colors care & fit\n"
        "targets: [description]\n"
        "summary: Reusable fit and care copy for every Comfort Colors listing.\n"
        "---\n" + _COMMON_COPY_BODY + "\n",
        encoding="utf-8",
    )


def test_common_copy_description_composes_into_the_printify_desired_document(
    browser_type: Any, workspace_root: Path, prerequisite_missing: Any
) -> None:
    _write_common_copy(workspace_root)
    edit_listing(
        workspace_root,
        etsy={
            "title": "Take A Hike Tee",
            # Lead only, no body source yet -- the browser interaction below
            # is what picks the common-copy file (section 6: "Choose a
            # common-copy item"), not a pre-seeded config.
            "description": {"lead": _LEAD},
            "tags": [],
            "renewal": "manual",
        },
    )
    set_shop_id(workspace_root, _SHOP_ID)
    write_design(workspace_root, _PRINT_AREA)

    catalog = FakeCatalogClient(
        blueprints=[_PRINTIFY_BLUEPRINT],
        providers_by_blueprint={706: [_PRINTIFY_PROVIDER]},
        variants_by_key={(706, 29): _printify_variants()},
    )
    printify = FakePrintifyClient([Shop(id=_SHOP_ID, title="My new store")])
    # Seeded before the product exists, exactly as `test_publish_stage.py`
    # does: `publish` attaches `external` and clears `is_locked` on its very
    # first read, so the `publish` stage that runs after `printify_product`
    # (unrelated to anything this test is about) does not spend real minutes
    # polling a fake that would otherwise stay locked forever.
    printify.publish_external["fake-product-1"] = ProductExternal(
        id="4572550919", handle="https://www.etsy.com/listing/4572550919/probe"
    )

    def _context_factory(workspace: Workspace, on_event: EventSink | None) -> RunContext:
        kwargs = {"on_event": on_event} if on_event is not None else {}
        return RunContext(
            workspace=workspace, catalog=catalog, printify=printify, etsy=None, **kwargs
        )

    with (
        _seo_server(
            workspace_root,
            prerequisite_missing,
            providers=[_ready_provider()],
            context_factory=_context_factory,
        ) as base_url,
        _seo_page(browser_type, base_url) as page,
    ):
        page.get_by_role("heading", name=LISTING).wait_for(state="visible")
        _open_details_tab(page)

        # -- The editor's preview is the exact server-side
        # `compose_description` call the deployment builder below will
        # also make. It stays behind the preview link until opened. --
        source_select = page.locator("#details-description-source")
        source_select.click()
        page.get_by_role("searchbox", name="Search description body sources").fill("comfort")
        page.get_by_role("option", name="Comfort Colors care & fit").click()
        expected_description = compose_description(_LEAD, _COMMON_COPY_BODY)
        page.get_by_role("button", name="Description preview").click()
        preview = page.locator("#details-description-preview .description-preview")
        for _ in range(100):
            if preview.inner_text() == expected_description:
                break
            page.wait_for_timeout(100)
        else:
            raise AssertionError(
                f"description preview never composed to the expected string: "
                f"{preview.inner_text()!r}"
            )

        # -- Deploy: a real plan against the real `printify_product`
        # stage, over the fake Printify/catalog clients above --
        page.get_by_role("button", name="Deploy changes →").click()
        page.wait_for_url(f"**/listings/{LISTING}/deploy")
        page.get_by_role("heading", name="Deploy").wait_for(state="visible")
        _wait_for_apply_enabled(page)

        page.get_by_role("button", name="Apply").click()
        page.get_by_text("Deployed.").wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)

    # -- The actual `printify_product` desired-document builder (PR2) is what
    # produced this -- not a client-side recomputation of the join rule --
    # because the browser drove a real Apply against the real fake Printify
    # client, exactly the way a seller's own Apply click would.
    assert len(printify.created) == 1
    assert printify.created[0].description == expected_description
    assert _LEAD in printify.created[0].description
    assert "Machine wash cold" in printify.created[0].description
