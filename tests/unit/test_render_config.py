from __future__ import annotations

import pytest
from pydantic import ValidationError

from etsy_listings.render.config import (
    ColourMatrixTemplate,
    DisplaceConfig,
    MultipleTemplate,
    Point,
    RenderConfig,
    ShadeConfig,
    SingleTemplate,
    load_template_config,
)

SQUARE_BOX = (
    Point(x=0.0, y=0.0),
    Point(x=100.0, y=0.0),
    Point(x=100.0, y=100.0),
    Point(x=0.0, y=100.0),
)


def _box_dicts(box: tuple[Point, Point, Point, Point]) -> list[dict[str, float]]:
    return [{"x": p.x, "y": p.y} for p in box]


def test_bounding_box_rejects_degenerate_quad() -> None:
    with pytest.raises(ValidationError, match="degenerate"):
        RenderConfig(
            bounding_box=(
                Point(x=0.0, y=0.0),
                Point(x=0.0, y=0.0),
                Point(x=0.0, y=0.0),
                Point(x=0.0, y=0.0),
            )
        )


def test_render_config_is_frozen() -> None:
    cfg = RenderConfig(bounding_box=SQUARE_BOX)
    with pytest.raises(ValidationError):
        cfg.bounding_box = SQUARE_BOX  # type: ignore[misc]


def test_canonical_json_is_deterministic() -> None:
    cfg = RenderConfig(bounding_box=SQUARE_BOX)
    assert cfg.canonical_json() == cfg.canonical_json()


def test_canonical_json_changes_with_content() -> None:
    a = RenderConfig(bounding_box=SQUARE_BOX)
    b = RenderConfig(bounding_box=SQUARE_BOX, shade=ShadeConfig(opacity=0.9))
    assert a.canonical_json() != b.canonical_json()


def test_displace_defaults_off_shade_defaults_on() -> None:
    assert DisplaceConfig().enabled is False
    assert ShadeConfig().enabled is True


def test_colour_matrix_template_has_no_per_colour_override() -> None:
    template = load_template_config(
        {"kind": "colour-matrix", "bounding_box": _box_dicts(SQUARE_BOX)}
    )
    assert isinstance(template, ColourMatrixTemplate)
    assert template.render_config().bounding_box == SQUARE_BOX


def test_multiple_template_dispatches_by_kind() -> None:
    template = load_template_config(
        {
            "kind": "multiple",
            "placements": [
                {"colour": "black", "bounding_box": _box_dicts(SQUARE_BOX)},
                {"colour": "ivory", "bounding_box": _box_dicts(SQUARE_BOX), "artwork": "on-dark"},
            ],
        }
    )
    assert isinstance(template, MultipleTemplate)
    assert template.colour_coverage == "exact"
    assert [p.colour for p in template.placements] == ["black", "ivory"]
    assert template.placements[1].artwork == "on-dark"
    assert template.render_config_for(template.placements[0]).bounding_box == SQUARE_BOX


def test_multiple_template_colour_coverage_accepts_subset() -> None:
    template = load_template_config(
        {
            "kind": "multiple",
            "colour_coverage": "subset",
            "placements": [{"colour": "black", "bounding_box": _box_dicts(SQUARE_BOX)}],
        }
    )
    assert isinstance(template, MultipleTemplate)
    assert template.colour_coverage == "subset"


def test_single_template_dispatches_by_kind() -> None:
    template = load_template_config(
        {"kind": "single", "colour": "black", "bounding_box": _box_dicts(SQUARE_BOX)}
    )
    assert isinstance(template, SingleTemplate)
    assert template.colour == "black"
    assert template.render_config().bounding_box == SQUARE_BOX


def test_single_template_colour_is_optional() -> None:
    template = load_template_config({"kind": "single", "bounding_box": _box_dicts(SQUARE_BOX)})
    assert isinstance(template, SingleTemplate)
    assert template.colour is None


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValidationError):
        load_template_config({"kind": "sometimes", "bounding_box": _box_dicts(SQUARE_BOX)})
