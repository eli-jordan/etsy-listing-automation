from __future__ import annotations

from dataclasses import replace

import numpy as np

from etsy_listings.core.render import MarigoldAppearance
from etsy_listings.core.render.material import MaterialLayer, render_marigold_scene

from tests.support.marigold import material_maps


def test_opaque_ink_uses_both_lighting_choices_without_garment_albedo() -> None:
    maps = material_maps()
    base = np.zeros((16, 16, 3), np.uint8)
    artwork = np.full((16, 16, 4), 255, np.uint8)
    layer = MaterialLayer(artwork, maps)
    estimated = np.array(
        render_marigold_scene(base, [layer], appearance=MarigoldAppearance(fabric_texture=0))
    )
    photographic = np.array(
        render_marigold_scene(
            base, [layer], appearance=MarigoldAppearance(lighting_source="photo", fabric_texture=0)
        )
    )
    unshaded = np.array(
        render_marigold_scene(
            base, [layer], appearance=MarigoldAppearance(lighting_strength=0, fabric_texture=0)
        )
    )
    assert estimated[8, 8].tolist() == [188, 188, 188]
    assert photographic[8, 8].tolist() == [255, 255, 255]
    assert unshaded[8, 8].tolist() == [255, 255, 255]
    hidden = replace(maps, visibility=np.zeros((16, 16), np.float32))
    np.testing.assert_array_equal(
        np.array(render_marigold_scene(base, [MaterialLayer(artwork, hidden)])), base
    )


def test_detail_controls_change_reflectance_without_changing_visibility() -> None:
    base = np.zeros((16, 16, 3), np.uint8)
    artwork = np.full((16, 16, 4), 128, np.uint8)
    artwork[..., 3] = 255
    layer = MaterialLayer(artwork, material_maps())
    smooth = np.array(
        render_marigold_scene(
            base, [layer], appearance=MarigoldAppearance(lighting_strength=0, fabric_texture=0)
        )
    )
    textured = np.array(
        render_marigold_scene(
            base, [layer], appearance=MarigoldAppearance(lighting_strength=0, fabric_texture=1)
        )
    )
    shiny = np.array(
        render_marigold_scene(
            base,
            [layer],
            appearance=MarigoldAppearance(lighting_strength=0, fabric_texture=0, print_shine=1),
        )
    )
    assert smooth[8, 8].tolist() == [128, 128, 128]
    assert textured[8, 8].tolist() == [134, 134, 134]
    assert shiny[8, 8].tolist() == [136, 136, 136]


def test_transparent_coloured_edges_do_not_bleed_and_background_stays_exact() -> None:
    maps = material_maps()
    maps.material[:] = [0.5, 0.5]
    maps.visibility[0] = 0
    artwork = np.full((2, 2, 4), [0, 255, 0, 0], np.uint8)
    artwork[0, 0] = [255, 0, 0, 255]
    base = np.full((16, 16, 3), [0, 0, 17], np.uint8)
    result = np.array(
        render_marigold_scene(
            base,
            [MaterialLayer(artwork, maps)],
            appearance=MarigoldAppearance(lighting_strength=0, fabric_texture=0),
        )
    )
    assert result[8, 8].tolist() == [137, 0, 13]
    np.testing.assert_array_equal(result[0], base[0])


def test_multiple_layers_use_their_maps_and_the_callers_composition_order() -> None:
    base = np.zeros((16, 16, 3), np.uint8)
    red = np.full((16, 16, 4), [255, 0, 0, 255], np.uint8)
    blue = np.full((16, 16, 4), [0, 0, 255, 255], np.uint8)
    left, right = material_maps(), material_maps()
    left.visibility[:, 10:] = 0
    right.visibility[:, :6] = 0
    a, b = MaterialLayer(red, left, "left"), MaterialLayer(blue, right, "right")
    settings = MarigoldAppearance(lighting_strength=0, fabric_texture=0)
    forward = np.array(render_marigold_scene(base, [a, b], appearance=settings))
    reverse = np.array(render_marigold_scene(base, [b, a], appearance=settings))
    assert forward[8, 3].tolist() == [255, 0, 0]
    assert forward[8, 8].tolist() == [0, 0, 255]
    assert reverse[8, 8].tolist() == [255, 0, 0]
    assert forward[8, 13].tolist() == [0, 0, 255]
