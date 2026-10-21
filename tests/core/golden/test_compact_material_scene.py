"""Full-photo pixels from a compact prepared field, including its blur halo."""

from pathlib import Path

import numpy as np

from etsy_listings.core.preparation.numerics import Evidence, EvidenceIdentity, plan_crop, prepare
from etsy_listings.core.render import MarigoldAppearance, MaterialLayer, render_marigold_scene


def compact_fixture():
    yy, xx = np.mgrid[:256, :256]
    base = np.stack([40 + xx // 2, 30 + yy // 2, 50 + (xx + yy) // 4], -1).astype(np.uint8)
    box = np.array([[80, 80], [160, 84], [156, 160], [76, 156]], np.float32)
    crop = plan_crop(box, (256, 256))
    width, height = crop.prediction_size
    normals = np.zeros((height, width, 3), np.float32)
    normals[..., 2] = 1
    evidence = Evidence(
        crop,
        EvidenceIdentity("p", "m", "i", "v"),
        normals,
        np.full((height, width, 3), 0.5, np.float32),
        np.full((height, width, 3), 0.4, np.float32),
        np.zeros((height, width, 3), np.float32),
        np.full((height, width), 0.5, np.float32),
    )
    mask = np.ones((256, 256), np.float32)
    mask[115:123, 117:125] = 0
    art = np.full((64, 64, 4), [0, 255, 0, 0], np.uint8)
    art[4:60, 4:60] = [255, 255, 255, 255]
    art[20:44, 20:44] = [220, 20, 80, 128]
    return base, box, evidence, mask, art


def test_compact_preparation_preserves_full_photo_pixels_and_blur_neighbours(assert_matches_golden):
    base, box, evidence, mask, art = compact_fixture()
    maps = prepare(base, box, evidence, mask=mask).maps
    assert maps.origin == (60, 64)
    assert maps.material.shape[0] < base.shape[0]
    image = render_marigold_scene(
        base,
        [MaterialLayer(art, maps)],
        appearance=MarigoldAppearance(lighting_source="photo", fabric_texture=0.75),
    )
    assert image.size == (256, 256)
    assert_matches_golden(image, Path(__file__).parent / "goldens" / "material-compact.png")


def test_editor_raster_keeps_photo_coordinates_and_composites_current_mask():
    base, box, evidence, mask, art = compact_fixture()
    maps = prepare(base, box, evidence, mask=mask, max_edge=128).maps
    image = render_marigold_scene(
        base[::2, ::2].copy(), [MaterialLayer(art, maps)], appearance=MarigoldAppearance()
    )
    assert image.size == (128, 128)
    pixels = np.asarray(image)
    assert np.array_equal(pixels[59, 60], base[118, 120])
    assert not np.array_equal(pixels[48, 48], base[96, 96])


def test_editor_composites_small_valid_placements_after_downsampling():
    base, box, evidence, mask, art = compact_fixture()
    box = (box - box[0]) * np.float32(0.4) + np.array([90, 90], np.float32)
    mask[:] = 1
    assert prepare(base, box, evidence, mask=mask).maps.size == (256, 256)
    preview = prepare(base, box, evidence, mask=mask, max_edge=64).maps
    image = render_marigold_scene(base[::4, ::4].copy(), [MaterialLayer(art, preview)])
    assert image.size == (64, 64)
    assert not np.array_equal(np.asarray(image)[26, 26], base[104, 104])


def test_editor_raster_samples_original_photo_pixel_centres():
    base, _, evidence, mask, _ = compact_fixture()
    box = np.array([[80, 80], [160, 80], [160, 160], [80, 160]], np.float32)
    mask[:] = 1
    maps = prepare(base, box, evidence, mask=mask, max_edge=128).maps
    # Output pixel 40 covers original pixels 80 and 81, centred at 80.5.
    # The flat 80px print therefore samples U=V=0.5/80, rather than zero.
    x, y = 40 - maps.origin[0], 40 - maps.origin[1]
    np.testing.assert_allclose(maps.material[y, x], [0.00625, 0.00625], atol=1e-6)
