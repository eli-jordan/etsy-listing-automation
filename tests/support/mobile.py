"""Phone-width checks shared by the browser tests that lay pages out on a phone."""

from __future__ import annotations

MOBILE_VIEWPORT = {"width": 390, "height": 844}


def assert_mobile_page_fits(page) -> None:
    """The page fits a phone: no sideways scroll, main spans it, nav is there."""
    dimensions = page.evaluate(
        """() => ({
            innerWidth: window.innerWidth,
            scrollWidth: document.documentElement.scrollWidth,
            main: (() => {
                const rect = document.querySelector('main').getBoundingClientRect();
                return {left: rect.left, right: rect.right, width: rect.width};
            })(),
            overflowing: [...document.querySelectorAll('*')]
                .filter((element) => element.getBoundingClientRect().right > window.innerWidth + 1)
                .slice(0, 10)
                .map((element) => ({
                    tag: element.tagName,
                    className: element.className,
                    right: element.getBoundingClientRect().right,
                })),
        })"""
    )
    assert dimensions["scrollWidth"] <= dimensions["innerWidth"], dimensions
    assert dimensions["main"]["left"] <= 1, dimensions
    assert dimensions["main"]["right"] <= dimensions["innerWidth"] + 1, dimensions
    assert dimensions["main"]["width"] >= dimensions["innerWidth"] - 1, dimensions

    navigation = page.get_by_role("navigation")
    navigation.get_by_role("link", name="Dashboard").wait_for(state="visible")
    navigation.get_by_role("link", name="Listings").wait_for(state="visible")


PHONE_CONTEXT = {
    "viewport": MOBILE_VIEWPORT,
    "device_scale_factor": 2,
    "is_mobile": True,
    "has_touch": True,
}
"""A phone as Playwright emulates one: the viewport, plus touch input and the
mobile viewport meta handling, so swipes and taps arrive as a finger's."""

PHONE_LANDSCAPE_CONTEXT = {**PHONE_CONTEXT, "viewport": {"width": 844, "height": 390}}
"""The same phone held sideways. Wider than the phone width, it gets the phone
layout from the query's sideways clause alone: a coarse pointer, landscape,
at most 500px tall (src/ui/src/phone/usePhone.ts)."""


def swipe(page, start: tuple[float, float], end: tuple[float, float], steps: int = 12) -> None:
    """One finger dragged from ``start`` to ``end`` (viewport pixels).

    Dispatched as touch events through the DevTools protocol, so the page
    sees ``pointerType == "touch"`` pointers exactly as from a real finger --
    Playwright's own touchscreen only taps. About 16ms a step, so the default
    is a brisk, deliberate swipe.

    After a drag dispatched this way, Chromium's touch emulation drops the
    ``click`` of the next touch tap about half the time -- on a bare HTML page
    with no app code too, and still 800ms later -- so a test that taps after a
    swipe uses ``locator.click()`` for that step, not ``locator.tap()``.
    """
    session = page.context.new_cdp_session(page)
    try:
        (x0, y0), (x1, y1) = start, end
        session.send(
            "Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x0, "y": y0}]}
        )
        for step in range(1, steps + 1):
            t = step / steps
            point = {"x": x0 + (x1 - x0) * t, "y": y0 + (y1 - y0) * t}
            session.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [point]})
            page.wait_for_timeout(16)
        session.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    finally:
        session.detach()


def pinch(page, centre: tuple[float, float], spread: float = 80, steps: int = 10) -> None:
    """Two fingers land a little apart around ``centre`` (the second just
    after the first, as a hand does) and spread ``spread`` pixels further
    apart along the diagonal, then lift."""
    session = page.context.new_cdp_session(page)
    try:
        x, y = centre

        def fingers(apart: float) -> list[dict]:
            return [
                {"x": x - 15 - apart, "y": y - apart, "id": 1},
                {"x": x + 15 + apart, "y": y + apart, "id": 2},
            ]

        first = fingers(0)[:1]
        session.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": first})
        page.wait_for_timeout(16)
        session.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": fingers(0)})
        for step in range(1, steps + 1):
            points = fingers(spread / 2 * step / steps)
            session.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": points})
            page.wait_for_timeout(16)
        session.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    finally:
        session.detach()
