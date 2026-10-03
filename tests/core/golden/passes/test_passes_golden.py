"""Per-pass goldens: each pass renders in isolation, so a regression names the
guilty pass rather than only showing a changed final composite.

Only ``warp`` reads the design. Every downstream pass starts from a frozen
prewarped layer (``fixtures/render/prewarped-grid.png``, a one-off copy of the
warp golden) and maps derived explicitly from the template photo, so a warp
defect fails the warp golden and the end-to-end composites but not these.
The fixture is an input, not a golden: never regenerate it from ``warp``."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from etsy_listings.core.render.config import DisplaceConfig, Point, ShadeConfig
from etsy_listings.core.render.io import load_design, load_template_base
from etsy_listings.core.render.maps import height_map, luminance_map
from etsy_listings.core.render.passes import displace, export, shade, warp

FIXTURES = Path(__file__).parents[3] / "fixtures"
DESIGN_PATH = FIXTURES / "render" / "grid-target.png"
TEMPLATE_BASE_PATH = FIXTURES / "mockup-templates" / "synthetic-tee" / "black.png"
PREWARPED_PATH = FIXTURES / "render" / "prewarped-grid.png"
GOLDENS = Path(__file__).parent / "goldens"

QUAD = (
    Point(x=60.0, y=40.0),
    Point(x=400.0, y=30.0),
    Point(x=410.0, y=500.0),
    Point(x=50.0, y=510.0),
)


def _template_size() -> tuple[int, int]:
    with Image.open(TEMPLATE_BASE_PATH) as img:
        return img.size  # (width, height)


def _prewarped() -> np.ndarray:
    with Image.open(PREWARPED_PATH) as img:
        return np.asarray(img.convert("RGBA"), dtype=np.uint8)


def test_warp_pass_golden(assert_matches_golden) -> None:
    design = load_design(DESIGN_PATH)
    result = warp(design, QUAD, _template_size())
    assert_matches_golden(Image.fromarray(result, mode="RGBA"), GOLDENS / "warp.png")


def test_displace_pass_golden(assert_matches_golden) -> None:
    template = load_template_base(TEMPLATE_BASE_PATH)
    warped = _prewarped()
    height = height_map(template)
    result = displace(warped, DisplaceConfig(enabled=True, strength=1.0), height)
    assert_matches_golden(Image.fromarray(result, mode="RGBA"), GOLDENS / "displace.png")


def test_shade_pass_golden(assert_matches_golden) -> None:
    template = load_template_base(TEMPLATE_BASE_PATH)
    warped = _prewarped()
    luminance = luminance_map(template)
    result = shade(warped, ShadeConfig(enabled=True, opacity=0.6, blend="soft-light"), luminance)
    assert_matches_golden(Image.fromarray(result, mode="RGBA"), GOLDENS / "shade.png")


def test_export_pass_golden(assert_matches_golden) -> None:
    template = load_template_base(TEMPLATE_BASE_PATH)
    warped = _prewarped()
    result = export(template, warped)
    assert_matches_golden(result, GOLDENS / "export.png")
