"""Browser test for Save as listing template (batch plan PR 1): the listing
editor, the *name it* page, the listing-templates endpoints and the files they
write, together in a real browser.

Save as listing template -> name it -> the card appears on the Listing
templates page, asserted on the ``template.yaml`` the UI actually wrote.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

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
