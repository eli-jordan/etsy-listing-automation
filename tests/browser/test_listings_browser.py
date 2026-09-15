"""Browser test for the listings UI (phase 5): the one thing no other layer
covers -- that the React app, the FastAPI listings endpoints and the real
filesystem work *together* in a browser. One full create -> edit -> autosave
sequence, asserted on the `listing.yaml` the UI actually wrote.

Runs against the built SPA served by FastAPI (see `conftest.py`), and skips
cleanly when playwright or its chromium build is missing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.browser


def _write_pricing_plan(workspace_root: Path) -> None:
    path = workspace_root / "pricing-plans" / "tee-basic.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "garment_profile": "comfort-colors-1717",
                "prices": {"S": "249 NOK", "M": "249 NOK"},
                "price_overrides": {},
            }
        ),
        encoding="utf-8",
    )


def _listing_yaml(workspace_root: Path, name: str) -> dict:  # noqa: ANN401
    return yaml.safe_load(
        (workspace_root / "listings" / name / "listing.yaml").read_text(encoding="utf-8")
    )


def test_create_edit_and_autosave_a_listing(page, workspace_root: Path) -> None:  # noqa: ANN001
    _write_pricing_plan(workspace_root)

    page.goto(page.url.rsplit("/", 1)[0] + "/listings")
    page.get_by_role("button", name="+ New listing").click()

    page.get_by_label("Name").fill("wildflower-crew")
    # The design/garment-profile selects populate from the workspace once
    # their fetches resolve -- waiting on the option proves the real
    # /api/listing-designs and /api/garment-profiles calls landed.
    page.get_by_label("Design").select_option("take-a-hike")
    page.get_by_label("Garment profile").select_option("comfort-colors-1717")
    page.get_by_role("button", name="Create").click()

    page.wait_for_url("**/listings/wildflower-crew")
    # The editor's own `getListing` fetch is still in flight right after the
    # navigation; wait for it rather than asserting the instant the URL
    # changes.
    page.get_by_role("heading", name="wildflower-crew").wait_for(state="visible")

    written = _listing_yaml(workspace_root, "wildflower-crew")
    assert written["garment_profile"] == "comfort-colors-1717"
    assert written["design"] == "../../designs/take-a-hike.png"
    assert written["media"] == []

    page.locator(".tabs .seg-opt", has_text="Listing Details").click()
    title = page.get_by_label("Title")
    title.fill("Wildflower Botanical Crew")
    # Blur flushes the debounced autosave immediately (useAutosave.flush),
    # rather than waiting out the 800ms debounce in a real browser.
    page.get_by_label("Description").click()

    # "Autosaved" is the settled state; "Saving…" is the one in flight. Waiting
    # on the settled word is what makes the assertion below a read of a file
    # the UI has finished writing rather than a race with it.
    page.wait_for_function(
        "document.querySelector('.page-head__meta')?.textContent?.includes('Autosaved')"
    )

    saved = _listing_yaml(workspace_root, "wildflower-crew")
    assert saved["etsy"]["title"] == "Wildflower Botanical Crew"

    # The title issue is gone; the still-empty colours/media stay reported.
    issues_text = page.locator(".issues").inner_text()
    assert "title" not in issues_text.lower()
    assert "no colours" in issues_text.lower() or "colours enabled" in issues_text.lower()
