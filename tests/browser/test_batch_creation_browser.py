"""Browser tests for batch creation (batch plan PR 2, PR 4 and PR 5): New batch,
the staging review, confirm, the summary and the batch AI queue, with the
real endpoints, the files they write and the queue's runs, in a real
browser.

* Drop three PNGs -> fix one name -> Create 3 listings -> the summary shows
  three rows, and each opens an editor whose design is the dropped file,
  asserted on the ``listing.yaml`` and ``designs/*.png`` the UI wrote.
* Create a batch of two -> both rows reach *done* on the summary -> the
  editor has the batch run's suggestions waiting (A40, A41).
* The summary -> a listing's name -> Mark reviewed in the editor -> Back to batch ->
  the summary shows the row reviewed, and the batch's record says so
  (batch plan PR 5; UI doc §7, §8).
* Drop a ZIP with nested folders, a duplicate, a text file and a design
  already in ``designs/`` -> the counts and rows match it, and the listing
  made from the known design names that file (batch plan PR 7).

The app is served with a :class:`~tests.support.ai_runs.ChainProvider` and
the in-memory Etsy market, so the queue drafts for real without a real CLI.
"""

from __future__ import annotations

import re
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
import yaml
from playwright.sync_api import expect

from etsy_listings.batches import BatchStore
from etsy_listings.workspace.workspace import Workspace

from tests.support.ai_runs import DRAFTED_BRIEF, ChainProvider, seed_prompts, seeded_market
from tests.support.batches import a_listing_template, png

pytestmark = pytest.mark.browser


@pytest.fixture
def app_options(workspace_root: Path) -> dict[str, Any]:
    """Staging refuses Create unless AI drafting could run (spec, *Design
    validation*), so the app gets a ready provider, the in-memory Etsy
    market and the three prompts."""
    seed_prompts(workspace_root)
    provider = ChainProvider()
    market = seeded_market()
    return {
        "seo_provider_factory": lambda _workspace: [provider],
        "market_client_factory": lambda _workspace: market,
    }


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

    page.get_by_text("Briefs are written for you", exact=False).wait_for()
    rows = page.locator("table.bc-table tbody tr")
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
        rows.filter(has_text=listing).get_by_role("link", name=listing).click()
        page.wait_for_url(re.compile(rf"/listings/{listing}\?batch="))
        # The editor's design row names the file the row wrote.
        design_file = page.locator(".design-row__file")
        design_file.wait_for()
        assert design_file.inner_text() == f"designs/{listing}.png"


def test_a_batch_of_two_drafts_both_and_the_editor_has_the_suggestions_waiting(  # noqa: ANN001
    page, workspace_root: Path
) -> None:
    a_listing_template(Workspace.discover(root_override=workspace_root))
    base = page.url.rsplit("/", 1)[0]
    page.goto(f"{base}/batches/new?template=heavyweight-tee")
    page.get_by_label("Design files").set_input_files(
        [
            {"name": name, "mimeType": "image/png", "buffer": png(seed)}
            for name, seed in {"lake-loop.png": 4, "pine-ridge-run.png": 5}.items()
        ]
    )
    page.get_by_role("button", name="Create 2 listings").click()

    done = page.get_by_text("Brief, market research and SEO done")
    expect(done).to_have_count(2)
    expect(page.locator(".bc-counts")).to_contain_text("2 drafted")
    expect(page.get_by_text("Ready to review")).to_have_count(2)
    for listing in ("lake-loop", "pine-ridge-run"):
        written = yaml.safe_load(
            (workspace_root / "listings" / listing / "listing.yaml").read_text(encoding="utf-8")
        )
        assert written["brief"] == DRAFTED_BRIEF

    page.locator("table.bc-table tbody tr", has_text="lake-loop").get_by_role(
        "link", name="lake-loop"
    ).click()
    page.wait_for_url(re.compile(r"/listings/lake-loop\?batch="))
    page.locator(".tabs .seg-opt", has_text="Listing Details").click()
    page.get_by_role("region", name="title AI suggestions").wait_for(state="visible")
    page.get_by_role("region", name="tag AI suggestions").wait_for(state="visible")


def test_open_from_the_summary_mark_reviewed_and_go_back_to_the_batch(  # noqa: ANN001
    page, workspace_root: Path
) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    a_listing_template(workspace)
    base = page.url.rsplit("/", 1)[0]
    page.goto(f"{base}/batches/new?template=heavyweight-tee")
    page.get_by_label("Design files").set_input_files(
        [{"name": "lake-loop.png", "mimeType": "image/png", "buffer": png(4)}]
    )
    page.get_by_role("button", name="Create 1 listing").click()
    expect(page.get_by_text("Brief, market research and SEO done")).to_have_count(1)
    counts = page.locator(".bc-counts")
    expect(counts).to_contain_text("0 of 1 reviewed")
    summary = page.url

    page.locator("table.bc-table tbody tr", has_text="lake-loop").get_by_role(
        "link", name="lake-loop"
    ).click()
    page.wait_for_url(re.compile(r"/listings/lake-loop\?batch="))
    page.get_by_role("button", name="Mark reviewed").click()
    expect(page.get_by_role("button", name="Reviewed")).to_have_attribute("aria-pressed", "true")
    page.get_by_role("button", name=re.compile("^Back to batch")).click()

    page.wait_for_url(summary)
    expect(counts).to_contain_text("1 of 1 reviewed")
    row = page.locator("table.bc-table tbody tr", has_text="lake-loop")
    expect(row.get_by_role("button", name="Reviewed")).to_be_visible()
    (batch,) = BatchStore(workspace).all()
    assert [r.reviewed for r in batch.rows] == [True]


def _zip(*entries: tuple[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return buffer.getvalue()


def test_drop_a_zip_with_folders_a_duplicate_and_a_text_file(  # noqa: ANN001
    page, workspace_root: Path
) -> None:
    """Batch plan PR 7: the counts and rows match the ZIP -- folder names
    dropped, the duplicate merged, the text file ignored and listed, and the
    design already in ``designs/`` reused -- and the listings Create makes
    say so on disk."""
    workspace = Workspace.discover(root_override=workspace_root)
    a_listing_template(workspace)
    workspace.design_file("fjord-mornings").write_bytes(png(4))
    archive = _zip(
        ("Night Hike Club.png", png(1)),
        ("exports/autumn/cedar-trail.png", png(2)),
        ("exports/cedar-trail copy.png", png(2)),
        ("exports/fjord-mornings-final.png", png(4)),
        ("readme.txt", b"Exported with Kittl"),
    )
    base = page.url.rsplit("/", 1)[0]
    page.goto(f"{base}/batches/new?template=heavyweight-tee")
    page.get_by_label("Design files").set_input_files(
        [{"name": "kittl-export.zip", "mimeType": "application/zip", "buffer": archive}]
    )

    page.get_by_role("heading", name="Review 3 designs").wait_for()
    counts = page.locator(".bc-counts")
    expect(counts).to_contain_text("3 ready")
    expect(counts).to_contain_text("1 duplicate merged")
    expect(counts).to_contain_text("1 other file ignored")
    listed = counts.get_by_text("readme.txt")
    expect(listed).to_be_hidden()
    counts.get_by_text("other file ignored").click()
    expect(listed).to_be_visible()

    names = [
        page.get_by_label(f"Listing name for {source}").input_value()
        for source in (
            "Night Hike Club.png",
            "exports/autumn/cedar-trail.png",
            "exports/fjord-mornings-final.png",
        )
    ]
    assert names == ["night-hike-club", "cedar-trail", "fjord-mornings-final"]
    rows = page.locator("table.bc-table tbody tr")
    expect(rows.filter(has_text="cedar-trail.png")).to_contain_text(
        "2 identical files, staged once"
    )
    expect(rows.filter(has_text="fjord-mornings-final.png")).to_contain_text(
        "Same image as designs/fjord-mornings.png. The listing reuses that file"
    )

    page.get_by_role("button", name="Create 3 listings").click()
    page.get_by_text("Briefs are written for you", exact=False).wait_for()
    listing = workspace_root / "listings" / "fjord-mornings-final" / "listing.yaml"
    written = yaml.safe_load(listing.read_text(encoding="utf-8"))
    assert written["design"] == {"default": "designs/fjord-mornings.png"}
    assert not (workspace_root / "designs" / "fjord-mornings-final.png").exists()
    assert (workspace_root / "designs" / "cedar-trail.png").read_bytes() == png(2)
