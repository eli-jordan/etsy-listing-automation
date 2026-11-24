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


def swipe(page, start: tuple[float, float], end: tuple[float, float], steps: int = 12) -> None:
    """One finger dragged from ``start`` to ``end`` (viewport pixels).

    Dispatched as touch events through the DevTools protocol, so the page
    sees ``pointerType == "touch"`` pointers exactly as from a real finger --
    Playwright's own touchscreen only taps. About 16ms a step, so the default
    is a brisk, deliberate swipe.
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
