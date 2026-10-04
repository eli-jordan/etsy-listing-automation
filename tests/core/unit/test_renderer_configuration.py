from __future__ import annotations

import pytest
from pydantic import ValidationError

from etsy_listings.core.render.config import load_template_config

BOX = [{"x": 0, "y": 0}, {"x": 100, "y": 0}, {"x": 100, "y": 100}, {"x": 0, "y": 100}]


def test_old_template_without_explicit_renderer_is_rejected() -> None:
    with pytest.raises(ValidationError, match="renderer"):
        load_template_config({"kind": "single", "bounding_box": BOX})


def test_marigold_defaults_and_refusal_are_explicit() -> None:
    template = load_template_config(
        {"kind": "single", "bounding_box": BOX, "renderer": {"type": "marigold", "config": {}}}
    )
    assert template.renderer.config.inference.num_inference_steps == 10
    assert template.renderer.config.appearance.fabric_texture == 0.25
    with pytest.raises(ValueError, match="Prepare the template first"):
        template.render_config()


@pytest.mark.parametrize("identifier", ["", "..", "../shirt", "a/b", "a\b", "con.", "a:b"])
def test_multiple_ids_are_safe(identifier: str) -> None:
    with pytest.raises(ValidationError, match="safe path segment"):
        load_template_config(
            {
                "kind": "multiple",
                "renderer": {"type": "photo-warp"},
                "placements": [{"id": identifier, "colour": "Ivory", "bounding_box": BOX}],
            }
        )


def test_placement_ids_are_unique_and_survive_reorder() -> None:
    data = {
        "kind": "multiple",
        "renderer": {"type": "photo-warp"},
        "placements": [
            {"id": "left-shirt", "colour": "Ivory", "bounding_box": BOX},
            {"id": "right-shirt", "colour": "Ivory", "bounding_box": BOX},
        ],
    }
    template = load_template_config(data)
    data["placements"].reverse()
    reordered = load_template_config(data)
    assert [p.id for p in reordered.placements] == ["right-shirt", "left-shirt"]
    data["placements"][0]["id"] = template.placements[0].id
    with pytest.raises(ValidationError, match="unique"):
        load_template_config(data)


@pytest.mark.parametrize("identifier", ["CON", "nul", "COM1", "lpt9"])
def test_ids_reject_windows_device_names(identifier: str) -> None:
    with pytest.raises(ValidationError, match="safe path segment"):
        load_template_config(
            {
                "kind": "multiple",
                "renderer": {"type": "photo-warp"},
                "placements": [{"id": identifier, "colour": "Ivory", "bounding_box": BOX}],
            }
        )


@pytest.mark.parametrize(
    "field,value", [("num_inference_steps", 0), ("ensemble_size", 1.5), ("ensemble_size", True)]
)
def test_inference_values_are_positive_strict_integers(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        load_template_config(
            {
                "kind": "single",
                "bounding_box": BOX,
                "renderer": {"type": "marigold", "config": {"inference": {field: value}}},
            }
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 1.1])
def test_appearance_strength_is_finite_and_bounded(value: float) -> None:
    with pytest.raises(ValidationError):
        load_template_config(
            {
                "kind": "single",
                "bounding_box": BOX,
                "renderer": {
                    "type": "marigold",
                    "config": {"appearance": {"fabric_texture": value}},
                },
            }
        )
