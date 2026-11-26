from __future__ import annotations

import pytest
from pydantic import ValidationError

from etsy_listings.core.render.config import (
    ColourMatrixTemplate,
    DisplaceConfig,
    MultipleTemplate,
    Point,
    RenderConfig,
    ShadeConfig,
    SingleTemplate,
    dump_template_config,
    load_template_config,
    scene_layers,
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


@pytest.mark.parametrize("value", [-0.01, 1.01, float("nan")])
def test_strength_and_opacity_are_refused_outside_zero_to_one(value: float) -> None:
    with pytest.raises(ValidationError):
        DisplaceConfig(strength=value)
    with pytest.raises(ValidationError):
        ShadeConfig(opacity=value)


def test_colour_matrix_template_has_no_per_colour_override() -> None:
    template = load_template_config(
        {
            "kind": "colour-matrix",
            "bounding_box": _box_dicts(SQUARE_BOX),
            "renderer": {"type": "photo-warp", "config": {}},
        }
    )
    assert isinstance(template, ColourMatrixTemplate)
    assert template.render_config().bounding_box == SQUARE_BOX


def test_multiple_template_dispatches_by_kind() -> None:
    template = load_template_config(
        {
            "kind": "multiple",
            "renderer": {"type": "photo-warp", "config": {}},
            "placements": [
                {
                    "id": "fixture-placement-1",
                    "colour": "black",
                    "bounding_box": _box_dicts(SQUARE_BOX),
                },
                {
                    "id": "fixture-placement-2",
                    "colour": "ivory",
                    "bounding_box": _box_dicts(SQUARE_BOX),
                },
            ],
        }
    )
    assert isinstance(template, MultipleTemplate)
    assert template.colour_coverage == "exact"
    assert [p.colour for p in template.placements] == ["black", "ivory"]
    assert template.render_config_for(template.placements[0]).bounding_box == SQUARE_BOX


def test_scene_layers_give_each_placement_its_colour_and_a_listing_box_only_its_own() -> None:
    moved = (
        Point(x=10.0, y=0.0),
        Point(x=90.0, y=0.0),
        Point(x=90.0, y=80.0),
        Point(x=10.0, y=80.0),
    )
    template = load_template_config(
        {
            "kind": "multiple",
            "renderer": {"type": "photo-warp", "config": {}},
            "placements": [
                {"id": "left", "colour": "black", "bounding_box": _box_dicts(SQUARE_BOX)},
                {"id": "right", "colour": "ivory", "bounding_box": _box_dicts(SQUARE_BOX)},
            ],
        }
    )

    layers = scene_layers(template, "moss", {"right": moved})

    assert [(colour, config.bounding_box) for colour, config in layers] == [
        ("black", SQUARE_BOX),
        ("ivory", moved),
    ]


def test_multiple_template_colour_coverage_accepts_subset() -> None:
    template = load_template_config(
        {
            "kind": "multiple",
            "colour_coverage": "subset",
            "renderer": {"type": "photo-warp", "config": {}},
            "placements": [
                {
                    "id": "fixture-placement-1",
                    "colour": "black",
                    "bounding_box": _box_dicts(SQUARE_BOX),
                }
            ],
        }
    )
    assert isinstance(template, MultipleTemplate)
    assert template.colour_coverage == "subset"


def test_single_template_dispatches_by_kind() -> None:
    template = load_template_config(
        {
            "kind": "single",
            "colour": "black",
            "bounding_box": _box_dicts(SQUARE_BOX),
            "renderer": {"type": "photo-warp", "config": {}},
        }
    )
    assert isinstance(template, SingleTemplate)
    assert template.colour == "black"
    assert template.render_config().bounding_box == SQUARE_BOX


def test_single_template_colour_is_optional() -> None:
    template = load_template_config(
        {
            "kind": "single",
            "bounding_box": _box_dicts(SQUARE_BOX),
            "renderer": {"type": "photo-warp", "config": {}},
        }
    )
    assert isinstance(template, SingleTemplate)
    assert template.colour is None


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValidationError):
        load_template_config({"kind": "sometimes", "bounding_box": _box_dicts(SQUARE_BOX)})


LABELLED_KINDS = [
    {"kind": "single", "bounding_box": _box_dicts(SQUARE_BOX)},
    {"kind": "colour-matrix", "bounding_box": _box_dicts(SQUARE_BOX)},
    {
        "kind": "multiple",
        "placements": [{"id": "a", "colour": "Black", "bounding_box": _box_dicts(SQUARE_BOX)}],
    },
]


def _template(shape: dict[str, object], **more: object) -> dict[str, object]:
    return {**shape, "renderer": {"type": "photo-warp", "config": {}}, **more}


@pytest.mark.parametrize("shape", LABELLED_KINDS, ids=lambda shape: str(shape["kind"]))
def test_every_kind_holds_labels_and_dumps_them(shape: dict[str, object]) -> None:
    template = load_template_config(_template(shape, labels=["theme:christmas", "cosy"]))

    assert template.labels == ["theme:christmas", "cosy"]
    assert dump_template_config(template)["labels"] == ["theme:christmas", "cosy"]


@pytest.mark.parametrize("shape", LABELLED_KINDS, ids=lambda shape: str(shape["kind"]))
def test_a_template_with_no_labels_dumps_no_key(shape: dict[str, object]) -> None:
    """An empty list in the dump would change every calibration revision and
    write the key into new files (spec *Storage*)."""
    assert "labels" not in dump_template_config(load_template_config(_template(shape)))
    assert "labels" not in dump_template_config(load_template_config(_template(shape, labels=[])))


def test_a_label_breaking_the_save_rules_still_loads() -> None:
    """A typo in a label cannot affect a pixel, so it must not stop a listing
    rendering: the rules apply on save, never on load (spec *Storage*)."""
    template = load_template_config(_template(LABELLED_KINDS[0], labels=["Bad_Label!", "x" * 99]))

    assert template.labels == ["Bad_Label!", "x" * 99]


@pytest.mark.parametrize("value", ["cosy", None, 7, {"theme": "christmas"}, ["cosy", 7], [None]])
def test_labels_that_are_not_a_list_of_strings_fail_to_load(value: object) -> None:
    with pytest.raises(ValidationError):
        load_template_config(_template(LABELLED_KINDS[0], labels=value))
