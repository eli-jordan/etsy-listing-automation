"""CPU sampling, lighting and mask goldens over synthetic pixels only."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from etsy_listings.core.render import MarigoldAppearance
from etsy_listings.core.render.material import MaterialLayer, render_marigold_scene

from tests.support.marigold import material_maps


@pytest.mark.parametrize("lighting", ["estimated", "photo"])
def test_linear_material_sampling_mask_and_detail_golden(assert_matches_golden, lighting) -> None:
    yy, xx = np.mgrid[:64, :64]
    base = np.stack([xx * 3, yy * 3, np.full_like(xx, 31)], -1).astype(np.uint8)
    maps = material_maps((64, 64))
    maps.material[..., 0] += 0.025 * np.sin(yy / 8)
    maps.visibility[:4] = 0
    maps.visibility[28:36, 28:36] = 0
    artwork = np.full((18, 18, 4), [0, 255, 0, 0], np.uint8)
    artwork[2:16, 2:16] = [255, 255, 255, 255]
    artwork[6:12, 6:12] = [220, 20, 80, 128]
    result = render_marigold_scene(
        base,
        [MaterialLayer(artwork, maps)],
        appearance=MarigoldAppearance(
            lighting_source=lighting, fabric_texture=0.75, print_shine=0.5
        ),
    )
    assert_matches_golden(result, Path(__file__).parent / "goldens" / f"material-{lighting}.png")
