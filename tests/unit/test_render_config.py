from __future__ import annotations

import pytest
from pydantic import ValidationError

from etsy_listings.render.config import (
    ColourOverride,
    DisplaceConfig,
    RenderConfig,
    ShadeConfig,
    TemplateConfig,
    WarpConfig,
)

SQUARE_QUAD = ((0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0))


def test_warp_config_rejects_degenerate_quad() -> None:
    with pytest.raises(ValidationError, match="degenerate"):
        WarpConfig(quad=((0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0)))


def test_render_config_is_frozen() -> None:
    cfg = RenderConfig(warp=WarpConfig(quad=SQUARE_QUAD))
    with pytest.raises(ValidationError):
        cfg.warp = WarpConfig(quad=SQUARE_QUAD)  # type: ignore[misc]


def test_canonical_json_is_deterministic() -> None:
    cfg = RenderConfig(warp=WarpConfig(quad=SQUARE_QUAD))
    assert cfg.canonical_json() == cfg.canonical_json()


def test_canonical_json_changes_with_content() -> None:
    a = RenderConfig(warp=WarpConfig(quad=SQUARE_QUAD))
    b = RenderConfig(warp=WarpConfig(quad=SQUARE_QUAD), shade=ShadeConfig(opacity=0.9))
    assert a.canonical_json() != b.canonical_json()


def test_template_config_resolve_uses_default_quad_absent_override() -> None:
    template = TemplateConfig(warp=WarpConfig(quad=SQUARE_QUAD))
    resolved = template.resolve("black")
    assert resolved.warp.quad == SQUARE_QUAD


def test_template_config_resolve_applies_per_colour_override() -> None:
    other_quad = ((0.0, 0.0), (50.0, 0.0), (50.0, 50.0), (0.0, 50.0))
    template = TemplateConfig(
        warp=WarpConfig(quad=SQUARE_QUAD),
        overrides={"moss": ColourOverride(warp=WarpConfig(quad=other_quad))},
    )
    assert template.resolve("moss").warp.quad == other_quad
    assert template.resolve("black").warp.quad == SQUARE_QUAD


def test_displace_defaults_off_shade_defaults_on() -> None:
    assert DisplaceConfig().enabled is False
    assert ShadeConfig().enabled is True
