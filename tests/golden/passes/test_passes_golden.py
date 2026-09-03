"""Per-pass goldens: each pass renders in isolation against the synthetic
grid/ruler target, so a regression names the guilty pass rather than only
showing a changed final composite."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from etsy_listings.render.config import DisplaceConfig, ShadeConfig, WarpConfig
from etsy_listings.render.io import load_design, load_template_base
from etsy_listings.render.maps import height_map, luminance_map
from etsy_listings.render.passes import displace, export, shade, warp

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"
DESIGN_PATH = FIXTURES / "render" / "grid-target.png"
TEMPLATE_BASE_PATH = FIXTURES / "mockup-templates" / "synthetic-tee" / "black.png"
GOLDENS = Path(__file__).parent / "goldens"

QUAD = ((60.0, 40.0), (400.0, 30.0), (410.0, 500.0), (50.0, 510.0))


def _template_size() -> tuple[int, int]:
    with Image.open(TEMPLATE_BASE_PATH) as img:
        return img.size  # (width, height)


def test_warp_pass_golden(assert_matches_golden) -> None:
    design = load_design(DESIGN_PATH)
    result = warp(design, WarpConfig(quad=QUAD), _template_size())
    assert_matches_golden(Image.fromarray(result, mode="RGBA"), GOLDENS / "warp.png")


def test_displace_pass_golden(assert_matches_golden) -> None:
    design = load_design(DESIGN_PATH)
    template = load_template_base(TEMPLATE_BASE_PATH)
    warped = warp(design, WarpConfig(quad=QUAD), _template_size())
    height = height_map(template)
    result = displace(warped, DisplaceConfig(enabled=True, strength=1.0), height)
    assert_matches_golden(Image.fromarray(result, mode="RGBA"), GOLDENS / "displace.png")


def test_shade_pass_golden(assert_matches_golden) -> None:
    design = load_design(DESIGN_PATH)
    template = load_template_base(TEMPLATE_BASE_PATH)
    warped = warp(design, WarpConfig(quad=QUAD), _template_size())
    luminance = luminance_map(template)
    result = shade(warped, ShadeConfig(enabled=True, opacity=0.6, blend="soft-light"), luminance)
    assert_matches_golden(Image.fromarray(result, mode="RGBA"), GOLDENS / "shade.png")


def test_export_pass_golden(assert_matches_golden) -> None:
    design = load_design(DESIGN_PATH)
    template = load_template_base(TEMPLATE_BASE_PATH)
    warped = warp(design, WarpConfig(quad=QUAD), _template_size())
    result = export(template, warped)
    assert_matches_golden(result, GOLDENS / "export.png")
