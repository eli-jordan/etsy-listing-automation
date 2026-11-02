"""Position mode on the Listing Images preview, against the real app.

What only this layer shows: the handles, driven by a real pointer and
keyboard, write a ``template_positions`` box that the Python pose maths and
the listing checks accept (the TypeScript twin and ``core.render.positions``
agree), Reset removes it, and Fit within limits repairs a refused one. Each
assertion is on the ``listing.yaml`` the UI wrote and the issues the server
reports for it (interactions: *Adjusting*, *Position outside the limits*).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import TypeAdapter

from etsy_listings.core.config.settings import TemplatePositionLimits
from etsy_listings.core.render.config import BoundingBox
from etsy_listings.core.render.positions import Pose, compose, decompose

pytestmark = pytest.mark.browser

LISTING = "take-a-hike"
TEMPLATE = "flat-lay-01"
LIMITS = TemplatePositionLimits()


def _listing_file(root: Path) -> Path:
    return root / "listings" / LISTING / "listing.yaml"


def _listing(root: Path) -> dict[str, Any]:
    return yaml.safe_load(_listing_file(root).read_text(encoding="utf-8"))


def _template_box(root: Path) -> BoundingBox:
    config = yaml.safe_load(
        (root / "mockup-templates" / TEMPLATE / "template.yaml").read_text(encoding="utf-8")
    )
    return TypeAdapter(BoundingBox).validate_python(config["bounding_box"])


def _corners(box: BoundingBox) -> list[dict[str, float]]:
    return [{"x": point.x, "y": point.y} for point in box]


def _write_positions(root: Path, positions: dict[str, Any]) -> None:
    listing = _listing(root)
    listing["template_positions"] = positions
    _listing_file(root).write_text(yaml.safe_dump(listing, sort_keys=False), encoding="utf-8")


def _wait_for(page: Any, root: Path, done: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    """Poll ``listing.yaml`` until ``done`` holds: the file is the effect."""
    listing = _listing(root)
    for _ in range(150):
        listing = _listing(root)
        if done(listing):
            return listing
        page.wait_for_timeout(100)
    raise AssertionError(f"listing.yaml never settled: {listing.get('template_positions')}")


def _pose(root: Path, listing: dict[str, Any]) -> Pose:
    """The stored box as ``plan`` sees it: a similarity within one pixel."""
    stored = TypeAdapter(BoundingBox).validate_python(
        listing["template_positions"][TEMPLATE]["bounding_box"]
    )
    fit = decompose(_template_box(root), stored)
    assert fit.residual_pixels < 1
    return fit.pose


def _positioned(root: Path, check: Callable[[Pose], bool]) -> Callable[[dict[str, Any]], bool]:
    def done(listing: dict[str, Any]) -> bool:
        return TEMPLATE in (listing.get("template_positions") or {}) and check(_pose(root, listing))

    return done


def _position_issues(page: Any) -> list[str]:
    response = page.request.get(page.url.split("/listings/")[0] + f"/api/listings/{LISTING}")
    return [
        issue["message"]
        for issue in response.json()["issues"]
        if issue["where"].startswith("template_positions")
    ]


def _open_images(page: Any) -> None:
    page.goto(page.url.rsplit("/", 1)[0] + f"/listings/{LISTING}")
    page.get_by_role("heading", name=LISTING).wait_for(state="visible")
    page.locator(".tabs .seg-opt", has_text="Listing Images").click()
    page.locator(f".rtile img[alt='{TEMPLATE} · black']").click()


def _drag(page: Any, target: Any, dx: float, dy: float) -> None:
    box = target.bounding_box()
    x = box["x"] + box["width"] / 2
    y = box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx / 2, y + dy / 2, steps=4)
    page.mouse.move(x + dx, y + dy, steps=4)
    page.mouse.up()


def test_move_resize_tilt_nudge_and_reset(page: Any, workspace_root: Path) -> None:
    _open_images(page)
    switch = page.get_by_role("switch", name="Adjust position")
    switch.click()
    box = page.get_by_role("button", name="Design position — drag to move, arrow keys to nudge")
    box.wait_for(state="visible")
    assert page.get_by_text("Applies to all 4 flat-lay-01 colours in this listing").is_visible()

    # Move: a short drag right, saved on release.
    _drag(page, box, 12, 0)
    listing = _wait_for(page, workspace_root, _positioned(workspace_root, lambda p: p.offset_x > 0))
    pose = _pose(workspace_root, listing)
    assert abs(pose.offset_y) < 0.02
    assert pose.scale == pytest.approx(1, abs=1e-6)

    # Resize: a corner pulled far out stops at the largest scale.
    _drag(page, page.get_by_label("Drag to resize").nth(2), 300, 300)
    _wait_for(
        page,
        workspace_root,
        _positioned(workspace_root, lambda p: p.scale == pytest.approx(LIMITS.scale.max)),
    )

    # Tilt: the round handle pulled far right stops at the rotation limit.
    _drag(page, page.get_by_label("Drag to tilt"), 400, 120)
    _wait_for(
        page,
        workspace_root,
        _positioned(workspace_root, lambda p: p.rotation == pytest.approx(LIMITS.rotation)),
    )

    # Nudge: Shift+Left steps 5% at a time and stops at the offset limit.
    box.focus()
    for _ in range(6):
        page.keyboard.press("Shift+ArrowLeft")
    listing = _wait_for(
        page,
        workspace_root,
        _positioned(workspace_root, lambda p: p.offset_x == pytest.approx(-LIMITS.offset)),
    )
    assert _position_issues(page) == []

    # Reset removes the entry rather than writing the template's box.
    page.get_by_role("button", name="Reset to template").click()
    _wait_for(page, workspace_root, lambda listing: "template_positions" not in listing)
    assert page.get_by_role("button", name="Reset to template").count() == 0


def test_fit_within_limits_repairs_a_refused_position(page: Any, workspace_root: Path) -> None:
    template_box = _template_box(workspace_root)
    stale = compose(template_box, Pose(scale=1.2, offset_x=-0.11, offset_y=0.0, rotation=0.0))
    _write_positions(workspace_root, {TEMPLATE: {"bounding_box": _corners(stale)}})

    _open_images(page)
    assert len(_position_issues(page)) == 2  # the scale and the offset
    switch = page.get_by_role("switch", name="Adjust position")
    assert switch.get_attribute("aria-checked") == "true"
    assert page.get_by_text("Outside the limits since the template's box moved").is_visible()

    page.get_by_role("button", name="Fit within limits").click()
    _wait_for(
        page,
        workspace_root,
        _positioned(
            workspace_root,
            lambda p: p.scale == pytest.approx(1.1) and p.offset_x == pytest.approx(-0.1),
        ),
    )
    assert switch.get_attribute("aria-checked") == "true"
    assert _position_issues(page) == []


def test_a_keyboard_repair_keeps_position_mode_and_focus(page: Any, workspace_root: Path) -> None:
    """A refused box opens in Position mode; nudging it back within the limits
    must not switch the mode off or drop keyboard focus mid-edit (G5)."""
    stale = compose(
        _template_box(workspace_root), Pose(scale=1.0, offset_x=-0.11, offset_y=0.0, rotation=0.0)
    )
    _write_positions(workspace_root, {TEMPLATE: {"bounding_box": _corners(stale)}})

    _open_images(page)
    switch = page.get_by_role("switch", name="Adjust position")
    switch.focus()
    for _ in range(10):
        page.keyboard.press("Shift+Tab")
        if (page.evaluate("document.activeElement.getAttribute('aria-label')") or "").startswith(
            "Design position"
        ):
            break
    assert page.evaluate("document.activeElement.matches(':focus-visible')")
    page.keyboard.press("ArrowRight")
    _wait_for(
        page,
        workspace_root,
        _positioned(workspace_root, lambda p: p.offset_x == pytest.approx(-0.1)),
    )
    page.wait_for_timeout(300)
    assert switch.get_attribute("aria-checked") == "true"
    assert (page.evaluate("document.activeElement.getAttribute('aria-label')") or "").startswith(
        "Design position"
    )
    assert _position_issues(page) == []


def test_a_stale_key_is_removed_from_its_issue_row(page: Any, workspace_root: Path) -> None:
    other = TypeAdapter(BoundingBox).validate_python(
        [{"x": 10, "y": 20}, {"x": 110, "y": 20}, {"x": 110, "y": 220}, {"x": 10, "y": 220}]
    )
    _write_positions(workspace_root, {"gone": {"bounding_box": _corners(other)}})

    _open_images(page)
    page.get_by_role("button", name="Remove template_positions.gone").click()
    _wait_for(page, workspace_root, lambda listing: "template_positions" not in listing)
    assert _position_issues(page) == []
