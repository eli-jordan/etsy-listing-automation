from __future__ import annotations

import pytest

from etsy_listings.config.slug import ColourExceptions, SlugCollisionError, slug_map, slugify


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Blue Jean", "blue-jean"),
        ("Black", "black"),
        ("Heather Grey", "heather-grey"),
        ("  Ivory  ", "ivory"),
        ("Red/White", "red-white"),
        ("S&M Blue (Limited)", "s-m-blue-limited"),
    ],
)
def test_slugify(name: str, expected: str) -> None:
    assert slugify(name) == expected


def test_slug_map_applies_exceptions_override() -> None:
    exceptions = ColourExceptions(root={"Ash & Grey": "ash-grey-special"})
    result = slug_map(["Ash & Grey", "Black"], exceptions)
    assert result == {"Ash & Grey": "ash-grey-special", "Black": "black"}


def test_slug_map_detects_collision() -> None:
    with pytest.raises(SlugCollisionError) as exc_info:
        slug_map(["Blue-Jean", "Blue Jean"], ColourExceptions(root={}))
    assert "blue-jean" in str(exc_info.value)


def test_slug_map_collision_resolved_by_exception() -> None:
    exceptions = ColourExceptions(root={"Blue-Jean": "blue-jean-alt"})
    result = slug_map(["Blue-Jean", "Blue Jean"], exceptions)
    assert result == {"Blue-Jean": "blue-jean-alt", "Blue Jean": "blue-jean"}
