"""Browser tests for the Listing templates page and how a template gets
there (batch plan PR 1, PR 6): the listing editor, the *name it* state, the
listing-templates and staging endpoints and the files they write, together in
a real browser.

* Save as listing template -> name it -> the card appears on the Listing
  templates page, asserted on the ``template.yaml`` the UI actually wrote.
* Dropping PNGs on a card lands on staging with that template chosen,
  skipping New batch (UI doc §2).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from etsy_listings.workspace.workspace import Workspace

from tests.support.batches import LISTING_TEMPLATE, a_listing_template, png

pytestmark = pytest.mark.browser


def test_save_a_listing_as_a_listing_template(page, workspace_root: Path) -> None:  # noqa: ANN001
    base = page.url.rsplit("/", 1)[0]
    page.goto(f"{base}/listings/take-a-hike")

    page.get_by_role("button", name="Save as listing template").click()

    # No dialog (UI doc §1): the draft opens straight away, unsaved, with the
    # name field focused, and nothing is on disk yet.
    name = page.get_by_label("Template name")
    name.wait_for(state="visible")
    assert page.get_by_text("Not saved — name this template to save it").is_visible()
    assert not (workspace_root / "listing-templates").exists()

    name.fill("heavyweight-tee")
    name.press("Enter")

    # Naming it writes it, and the editor stays open on it by name (PR 6).
    page.wait_for_url("**/listing-templates/heavyweight-tee")
    page.get_by_text("listing-templates/heavyweight-tee/template.yaml").wait_for()
    page.locator(".page-head__crumb", has_text="Listing templates").click()

    card = page.locator("article.bc-card", has_text="heavyweight-tee")
    card.wait_for(state="visible")
    assert "4 colours" in card.inner_text()
    assert page.get_by_text("1 template").is_visible()

    written = yaml.safe_load(
        (workspace_root / "listing-templates" / "heavyweight-tee" / "template.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert written["colors"] == ["black", "blue-jean", "ivory", "moss"]
    assert "design" not in written
    assert "brief" not in written


def test_dropping_pngs_on_a_card_lands_on_staging_with_that_template(  # noqa: ANN001
    page, workspace_root: Path
) -> None:
    a_listing_template(Workspace.discover(root_override=workspace_root))
    base = page.url.rsplit("/", 1)[0]
    page.goto(f"{base}/listing-templates")
    card = page.locator("article.bc-card", has_text=LISTING_TEMPLATE)
    card.wait_for()

    # A drag's files, as the browser hands them to the drop handlers.
    transfer = page.evaluate_handle(
        """(designs) => {
            const transfer = new DataTransfer();
            for (const [name, bytes] of designs) {
                transfer.items.add(new File([new Uint8Array(bytes)], name, { type: "image/png" }));
            }
            return transfer;
        }""",
        [["night-hike.png", list(png(1))], ["cedar-trail.png", list(png(2))]],
    )
    card.dispatch_event("dragenter", {"dataTransfer": transfer})
    assert card.get_by_text("Drop to stage 2 PNGs").is_visible()
    card.dispatch_event("drop", {"dataTransfer": transfer})

    page.wait_for_url("**/batches/staging/*")
    page.get_by_role("heading", name="Review 2 designs").wait_for()
    assert page.locator("strong", has_text=LISTING_TEMPLATE).is_visible()
