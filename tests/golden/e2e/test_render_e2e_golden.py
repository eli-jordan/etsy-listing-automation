"""End-to-end golden composites: the full pipeline (warp -> shade -> export,
displace off by default) against each colour of the synthetic template set."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from etsy_listings.render.config import TemplateConfig
from etsy_listings.render.io import load_design, load_template_base
from etsy_listings.render.maps import height_map, luminance_map
from etsy_listings.render.pipeline import render

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"
DESIGN_PATH = FIXTURES / "render" / "grid-target.png"
TEMPLATE_DIR = FIXTURES / "mockup-templates" / "synthetic-tee"
GOLDENS = Path(__file__).parent / "goldens"


@pytest.mark.parametrize("colour", ["black", "white"])
def test_e2e_composite_golden(colour: str, assert_matches_golden) -> None:  # noqa: ANN001
    template_config = TemplateConfig.model_validate(
        yaml.safe_load((TEMPLATE_DIR / "template.yaml").read_text(encoding="utf-8"))
    )
    cfg = template_config.resolve(colour)

    design = load_design(DESIGN_PATH)
    base = load_template_base(TEMPLATE_DIR / f"{colour}.png")
    luminance = luminance_map(base)
    height = height_map(base)

    result = render(design, base, cfg, height=height, luminance=luminance)
    assert_matches_golden(result, GOLDENS / f"{colour}.png")


def test_e2e_composite_with_displace_enabled_golden(assert_matches_golden) -> None:  # noqa: ANN001
    template_config = TemplateConfig.model_validate(
        yaml.safe_load((TEMPLATE_DIR / "template.yaml").read_text(encoding="utf-8"))
    )
    cfg = template_config.resolve("black").model_copy(
        update={
            "displace": template_config.displace.model_copy(
                update={"enabled": True, "strength": 0.6}
            )
        }
    )

    design = load_design(DESIGN_PATH)
    base = load_template_base(TEMPLATE_DIR / "black.png")
    luminance = luminance_map(base)
    height = height_map(base)

    result = render(design, base, cfg, height=height, luminance=luminance)
    assert_matches_golden(result, GOLDENS / "black-displaced.png")
