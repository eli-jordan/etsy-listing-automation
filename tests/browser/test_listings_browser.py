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


def _wait_for_listing(page, workspace_root: Path, name: str, **fields: object) -> dict:  # noqa: ANN001,ANN401
    """Poll `listing.yaml` until the UI has written *fields* into it.

    The page cannot be waited on for this: "Autosaved" is the *settled* caption,
    so it already reads true during the 800ms debounce before a save has even
    been sent. The file is the observable effect this layer exists to check, so
    the file is what gets waited on.
    """
    for _ in range(100):
        written = _listing_yaml(workspace_root, name)
        if all(written.get(key) == value for key, value in fields.items()):
            return written
        page.wait_for_timeout(100)
    raise AssertionError(f"{name}/listing.yaml never reached {fields}: {written}")


def test_create_name_and_autosave_a_listing(page, workspace_root: Path) -> None:  # noqa: ANN001
    """`+ New listing` opens the editor on nothing, and the listing appears on
    disk the moment it has a name (PRD 70).

    It used to need a price source as well, and this test asserted that: the
    file stayed missing while the head explained what was in the way. That was
    the one incompleteness out of eight that withheld the file rather than
    only the deploy.
    """
    _write_pricing_plan(workspace_root)

    page.goto(page.url.rsplit("/", 1)[0] + "/listings")
    page.get_by_role("button", name="+ New listing").click()

    # There is no create *form* -- this is the editor, on a draft the server
    # built (`GET /api/listing-draft`) with nothing chosen. Waiting for the
    # garment-profile select proves that fetch landed and the tabs are live on
    # a listing that does not exist.
    page.get_by_label("Garment profile").wait_for(state="visible")
    assert not (workspace_root / "listings" / "wildflower-crew").exists()

    # Everything still to pick is in the banner, which is the only way an
    # unsaved listing can be told what it is missing.
    issues_text = page.locator(".issues").inner_text().lower()
    assert "garment profile" in issues_text
    assert "design" in issues_text

    page.get_by_label("Listing name").fill("wildflower-crew")
    page.get_by_label("Listing name").press("Enter")

    # Naming it wrote it, with no garment profile, no design, no colours and
    # no price source. All four are still in the banner, where they block
    # deploying it.
    page.wait_for_url("**/listings/wildflower-crew")
    page.get_by_role("heading", name="wildflower-crew").wait_for(state="visible")
    written = _listing_yaml(workspace_root, "wildflower-crew")
    assert written["pricing_plan"] is None
    assert written["media"] == []
    assert "pricing plan" in page.locator(".issues").inner_text().lower()

    # And a price source is an ordinary edit from here, not a second create.
    page.locator(".tabs .seg-opt", has_text="Pricing").click()
    page.get_by_label("Plan", exact=True).select_option(label="tee-basic")
    _wait_for_listing(
        page,
        workspace_root,
        "wildflower-crew",
        pricing_plan="../../pricing-plans/tee-basic.yaml",
    )

    # And from here it is an ordinary listing: autosave patches it.
    page.locator(".tabs .seg-opt", has_text="Variants").click()
    page.get_by_label("Garment profile").select_option("comfort-colors-1717")
    _wait_for_listing(
        page, workspace_root, "wildflower-crew", garment_profile="comfort-colors-1717"
    )


def test_renaming_a_listing_moves_its_directory_and_render_cache(
    page,  # noqa: ANN001
    workspace_root: Path,
) -> None:
    cached = workspace_root / ".cache" / "renders" / "take-a-hike" / "flat-lay-01"
    cached.mkdir(parents=True, exist_ok=True)
    (cached / "black.png").write_bytes(b"not really a png")

    page.goto(page.url.rsplit("/", 1)[0] + "/listings/take-a-hike")
    page.get_by_role("heading", name="take-a-hike").dblclick()

    name = page.get_by_label("Listing name")
    name.fill("hike-away")
    name.press("Enter")

    page.wait_for_url("**/listings/hike-away")
    page.get_by_role("heading", name="hike-away").wait_for(state="visible")

    assert not (workspace_root / "listings" / "take-a-hike").exists()
    assert (workspace_root / "listings" / "hike-away" / "listing.yaml").is_file()
    moved = workspace_root / ".cache" / "renders" / "hike-away" / "flat-lay-01" / "black.png"
    assert moved.read_bytes() == b"not really a png"


def test_a_taken_name_is_refused_without_losing_the_draft(
    page,  # noqa: ANN001
    workspace_root: Path,
) -> None:
    _write_pricing_plan(workspace_root)

    page.goto(page.url.rsplit("/", 1)[0] + "/listings/new")
    page.get_by_label("Garment profile").wait_for(state="visible")
    page.get_by_label("Garment profile").select_option("comfort-colors-1717")

    page.get_by_label("Listing name").fill("take-a-hike")
    page.get_by_label("Listing name").press("Enter")

    page.get_by_role("alert").wait_for(state="visible")
    # Still the draft, still carrying the edit made before the name was tried.
    assert page.url.endswith("/listings/new")
    assert page.get_by_label("Garment profile").input_value() == "comfort-colors-1717"


def test_switching_a_colour_off_stays_off(page, workspace_root: Path) -> None:  # noqa: ANN001
    """The bug this covers: the switch snapped straight back on.

    `colors:` alone failed `listing.yaml`'s own validator server-side, which
    answers 200 with the listing *unchanged* -- so the editor re-rendered the
    colour as enabled and the reason never reached the screen. It needs the
    whole stack to reproduce (real validator, real autosave, real file), which
    is exactly what this layer is for.
    """
    page.goto(page.url.rsplit("/", 1)[0] + "/listings/take-a-hike")
    page.get_by_role("heading", name="take-a-hike").wait_for(state="visible")

    switch = page.get_by_role("switch", name="moss")
    # Waiting on the PATCH itself, not on the "Autosaved" caption: that
    # caption is also the *settled* state, so it is already true before the
    # 800ms debounce has fired and reading the file on it would be a race.
    with page.expect_response(
        lambda r: r.url.endswith("/api/listings/take-a-hike") and r.request.method == "PATCH"
    ):
        switch.click()

    saved = _listing_yaml(workspace_root, "take-a-hike")
    assert "moss" not in saved["colors"]
    # The mockup that referenced it went with it -- an image for a variant
    # that no longer exists is what the server would have refused.
    assert not any(
        isinstance(entry, dict) and entry.get("colour") == "moss" for entry in saved["media"]
    )
    # The file is the assertion, not the switch: what re-enabled it was the
    # server refusing the write and answering with the unchanged listing, so a
    # `listing.yaml` that no longer sells the colour is the thing that was
    # actually wrong. (The row itself is gone here -- the fixture garment
    # profile classifies no colours, so a colour the listing has dropped is no
    # longer one this tab knows about.)


def test_the_shade_buttons_need_a_profile_that_classifies_its_colours(page) -> None:  # noqa: ANN001
    """Dark/Light are driven by the garment profile's light/dark map, and the
    fixture profile declares none -- so with nothing to act on they are not
    offered at all, rather than offered and silently doing nothing."""
    page.goto(page.url.rsplit("/", 1)[0] + "/listings/take-a-hike")
    page.get_by_role("heading", name="take-a-hike").wait_for(state="visible")
    page.get_by_role("switch", name="moss").wait_for(state="visible")

    assert page.get_by_role("button", name="Dark").count() == 0
    assert page.get_by_role("button", name="Light").count() == 0
