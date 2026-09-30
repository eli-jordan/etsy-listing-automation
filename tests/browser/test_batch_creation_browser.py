"""Browser test for batch creation (batch plan PR 2): New batch, the staging
review, confirm and the summary, with the real endpoints and the files they
write, in a real browser.

Drop three PNGs -> fix one name -> Create 3 listings -> the summary shows
three rows, and each opens an editor whose design is the dropped file,
asserted on the ``listing.yaml`` and ``designs/*.png`` the UI wrote.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from etsy_listings.workspace.workspace import Workspace

from tests.support.batches import a_listing_template, png

pytestmark = pytest.mark.browser

DESIGNS = {"Night Hike Club.png": 1, "cedar-trail.png": 2, "★★★.png": 3}


def test_drop_three_pngs_fix_a_name_and_create_three_listings(  # noqa: ANN001
    page, workspace_root: Path
) -> None:
    a_listing_template(Workspace.discover(root_override=workspace_root))
    base = page.url.rsplit("/", 1)[0]
    page.goto(f"{base}/listing-templates")

    page.locator("article.bc-card", has_text="heavyweight-tee").get_by_role(
        "link", name="Start batch"
    ).click()
    assert page.get_by_role("radio", name="heavyweight-tee").get_attribute("aria-checked") == "true"
    page.get_by_label("Design files").set_input_files(
        [
            {"name": name, "mimeType": "image/png", "buffer": png(seed)}
            for name, seed in DESIGNS.items()
        ]
    )

    page.get_by_role("heading", name="Review 3 designs").wait_for()
    create = page.get_by_role("button", name="Create 3 listings")
    assert create.is_disabled()
    assert page.get_by_text("Fix 1 name to create the listings.").is_visible()

    name = page.get_by_label("Listing name for ★★★.png")
    name.fill("summit-coffee")
    name.press("Enter")
    page.get_by_text("Each listing is a local draft. Nothing goes to Printify or Etsy.").wait_for()
    create.click()

    rows = page.locator("table.bc-table tbody tr")
    page.get_by_text("3 of 3 listings created").wait_for()
    assert rows.count() == 3
    names = ["night-hike-club", "cedar-trail", "summit-coffee"]
    for listing, seed in zip(names, DESIGNS.values(), strict=True):
        written = yaml.safe_load(
            (workspace_root / "listings" / listing / "listing.yaml").read_text(encoding="utf-8")
        )
        assert written["design"] == {"default": f"designs/{listing}.png"}
        assert (workspace_root / "designs" / f"{listing}.png").read_bytes() == png(seed)

    summary = page.url
    for listing in names:
        page.goto(summary)
        rows.filter(has_text=listing).get_by_role("link", name="Open").click()
        page.wait_for_url(f"**/listings/{listing}")
        # The editor's design row names the file the row wrote.
        design_file = page.locator(".design-row__file")
        design_file.wait_for()
        assert design_file.inner_text() == f"designs/{listing}.png"
