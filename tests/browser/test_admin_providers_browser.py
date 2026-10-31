"""Admin AI providers through the built SPA, real settings API and fixture files (PR 5).

Model discovery is served by route interception: the host's own discovery is
replaced in browser tests, and its CLI contracts have unit tests.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from etsy_listings.core.config.settings import Settings
from etsy_listings.core.workspace.workspace import Workspace

pytestmark = pytest.mark.browser

EFFORTS = ["low", "medium", "high", "xhigh", "max"]
LOADED = {
    "cache_seconds": 1800,
    "providers": {
        "claude": {
            "models": [{"id": "claude-opus-5-5", "label": "claude-opus-5-5", "efforts": []}],
            "efforts": EFFORTS,
        },
        "codex": {
            "models": [{"id": "gpt-6.1-sol", "label": "GPT-6.1-Sol", "efforts": EFFORTS}],
            "efforts": [],
        },
        "grok": {
            "models": [{"id": "grok-4.7", "label": "grok-4.7", "efforts": []}],
            "efforts": ["low", "medium", "high"],
        },
    },
}
UNREADABLE = {"models": [], "efforts": [], "problem": "The CLI did not answer."}
FAILED = {
    "cache_seconds": 1800,
    "providers": dict.fromkeys(["claude", "codex", "grok"], UNREADABLE),
}
SOURCE = """\
batch_ai:
  concurrency: 2  # kept through provider edits
ai:
  providers:
    - name: claude
      model: claude-opus-5-5
      effort: high
    - name: codex
      model: gpt-6.1-sol
    - name: grok
      enabled: false
      model: grok-4.4
"""


@pytest.fixture
def expect(browser_type):  # noqa: ANN001, ANN201 - optional Playwright after prerequisite check
    from playwright.sync_api import expect as playwright_expect

    return playwright_expect


@pytest.fixture(params=["light", "dark"])
def theme(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def capture(page, theme: str, state: str) -> None:  # noqa: ANN001
    if directory := os.environ.get("ADMIN_PROVIDERS_SCREENSHOT_DIR"):
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target / f"app-{state}-{theme}.png"))


def serve_models(page, first: dict, refreshed: dict) -> list[str]:  # noqa: ANN001
    requests: list[str] = []

    def fulfil(route) -> None:  # noqa: ANN001
        requests.append(route.request.url)
        route.fulfill(json=refreshed if "refresh=true" in route.request.url else first)

    page.route("**/api/admin/settings/models*", fulfil)
    return requests


def open_settings(page, base: str, theme: str) -> None:  # noqa: ANN001
    page.set_viewport_size({"width": 1280, "height": 800})
    page.emulate_media(color_scheme=theme)
    page.goto(f"{base}/admin")
    page.get_by_role("link", name="Settings settings.yaml").click()


def is_save(response) -> bool:  # noqa: ANN001
    return response.url.endswith("/api/admin/settings") and response.request.method == "PATCH"


def test_keyboard_reorder_and_toggles_save_the_ordered_list_and_keep_stale_choices(
    page,
    expect,
    calibrator_server: str,
    workspace_root: Path,
    theme: str,  # noqa: ANN001
) -> None:
    path = Workspace.discover(root_override=workspace_root).settings_file()
    path.write_text(SOURCE, encoding="utf-8")
    serve_models(page, LOADED, LOADED)
    open_settings(page, calibrator_server, theme)
    expect(page.get_by_text("Model lists loaded. Cached for 30 minutes.")).to_be_visible()
    expect(page.get_by_text("grok-4.4 is no longer offered by the Grok CLI.")).to_be_visible()
    capture(page, theme, "providers")

    with page.expect_response(is_save):
        page.get_by_role("button", name="Move Codex. Use the up and down arrow keys.").press(
            "ArrowUp"
        )
    expect(
        page.get_by_role("button", name="Move Codex. Use the up and down arrow keys.")
    ).to_be_focused()
    providers = Settings.load(path).ai.providers
    assert [p.name for p in providers] == ["codex", "claude", "grok"]
    assert "# kept through provider edits" in path.read_text(encoding="utf-8")

    with page.expect_response(is_save):
        page.get_by_role("button", name="Grok is off. Turn it on").click()
    grok = Settings.load(path).ai.providers[2]
    assert (grok.enabled, grok.model) == (True, "grok-4.4")
    expect(page.get_by_role("combobox", name="Grok model")).to_have_value("grok-4.4")

    for name in ["Codex is step 1. Turn it off", "Claude is step 1. Turn it off"]:
        with page.expect_response(is_save):
            page.get_by_role("button", name=name).click()
    page.get_by_role("button", name="Grok is step 1. Turn it off").click()
    expect(page.get_by_text("At least one provider stays on")).to_be_visible()
    assert [p.enabled for p in Settings.load(path).ai.providers] == [False, False, True]


def test_discovery_failure_keeps_saved_choices_until_refresh_reads_the_lists(
    page,
    expect,
    calibrator_server: str,
    workspace_root: Path,
    theme: str,  # noqa: ANN001
) -> None:
    path = Workspace.discover(root_override=workspace_root).settings_file()
    path.write_text(SOURCE, encoding="utf-8")
    requests = serve_models(page, FAILED, LOADED)
    open_settings(page, calibrator_server, theme)
    expect(page.get_by_role("alert")).to_contain_text("Could not read the model lists.")
    expect(page.get_by_role("combobox", name="Claude model")).to_have_value("claude-opus-5-5")
    expect(page.get_by_role("combobox", name="Claude reasoning")).to_have_value("high")
    expect(page.get_by_text("not offered")).to_have_count(0)
    capture(page, theme, "discovery")

    page.get_by_role("button", name="Refresh lists").click()
    expect(page.get_by_text("Model lists loaded. Cached for 30 minutes.")).to_be_visible()
    expect(page.get_by_role("alert")).to_have_count(0)
    assert ["refresh=true" in url for url in requests] == [False, True]
    assert path.read_text(encoding="utf-8") == SOURCE
    capture(page, theme, "refreshed")


def test_startup_discovery_status_keeps_saved_preferences_and_allows_refresh(
    page,
    expect,
    calibrator_server: str,
    workspace_root: Path,
    theme: str,
) -> None:
    path = Workspace.discover(root_override=workspace_root).settings_file()
    path.write_text(SOURCE, encoding="utf-8")
    pending = {
        "cache_seconds": 1800,
        "providers": {
            **LOADED["providers"],
            "codex": {
                **LOADED["providers"]["codex"],
                "problem": "Model discovery is in progress. Refresh to check again.",
            },
        },
    }
    serve_models(page, pending, LOADED)
    open_settings(page, calibrator_server, theme)
    expect(
        page.get_by_text("Model discovery is in progress. Refresh to check again.")
    ).to_be_visible()
    expect(page.get_by_role("combobox", name="Codex model")).to_have_value("gpt-6.1-sol")
    expect(page.get_by_role("combobox", name="Codex reasoning")).to_have_value("")
    capture(page, theme, "discovery-pending")
    page.get_by_role("button", name="Refresh lists").click()
    expect(page.get_by_text("Model lists loaded. Cached for 30 minutes.")).to_be_visible()
    assert path.read_text(encoding="utf-8") == SOURCE
