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
