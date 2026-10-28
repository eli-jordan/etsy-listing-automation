"""The design an AI provider looks at: transparency flattened onto a
background the artwork can be seen against."""

from pathlib import Path

from PIL import Image

from etsy_listings.core.ai.viewable import DARK_BACKGROUND, LIGHT_BACKGROUND, viewable_design


def _artwork(path: Path, ink: tuple[int, int, int], *, mode: str = "RGBA") -> Path:
    """A transparent canvas with one opaque square of ``ink`` in the middle,
    and fully transparent pixels stored as black -- the case that hides black
    artwork."""
    image = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    image.paste((*ink, 255), (10, 10, 30, 30))
    image.convert(mode).save(path)
    return path


def test_black_artwork_on_transparency_is_shown_on_white(tmp_path: Path) -> None:
    source = _artwork(tmp_path / "black-text.png", (0, 0, 0))

    viewable = viewable_design(source, tmp_path / "cache")

    with Image.open(viewable) as image:
        assert image.mode == "RGB"
        assert image.getpixel((0, 0)) == LIGHT_BACKGROUND
        assert image.getpixel((20, 20)) == (0, 0, 0)
    assert viewable.name == "black-text.png"
    assert viewable.parent.parent == tmp_path / "cache"


def test_white_artwork_on_transparency_is_shown_on_charcoal(tmp_path: Path) -> None:
    source = _artwork(tmp_path / "white-text.png", (255, 255, 255))

    with Image.open(viewable_design(source, tmp_path / "cache")) as image:
        assert image.getpixel((0, 0)) == DARK_BACKGROUND
        assert image.getpixel((20, 20)) == (255, 255, 255)


def test_an_opaque_design_is_handed_over_as_it_is(tmp_path: Path) -> None:
    opaque = tmp_path / "opaque.png"
    Image.new("RGB", (8, 8), (0, 0, 0)).save(opaque)
    full_alpha = tmp_path / "full-alpha.png"
    Image.new("RGBA", (8, 8), (0, 0, 0, 255)).save(full_alpha)

    assert viewable_design(opaque, tmp_path / "cache") == opaque
    assert viewable_design(full_alpha, tmp_path / "cache") == full_alpha
    assert not (tmp_path / "cache").exists()


def test_an_edited_design_gets_a_fresh_copy(tmp_path: Path) -> None:
    source = _artwork(tmp_path / "design.png", (0, 0, 0))
    first = viewable_design(source, tmp_path / "cache")
    _artwork(source, (255, 255, 255))

    second = viewable_design(source, tmp_path / "cache")

    assert second != first
    with Image.open(second) as image:
        assert image.getpixel((20, 20)) == (255, 255, 255)
