"""The create-mockup-template-cc1717 skill's `match_grain`: how a generated clean-up patch's
grain is brought to the level of the original around it."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

SCRIPT = Path(__file__).parents[1] / ".claude/skills/create-mockup-template-cc1717/recolour.py"


@pytest.fixture(scope="module")
def recolour() -> ModuleType:
    spec = importlib.util.spec_from_file_location("recolour", SCRIPT)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["recolour"] = module
    spec.loader.exec_module(module)
    return module


def noisy(size: int, sigma: float, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.clip(rng.normal(60, sigma, (size, size, 3)), 0, 255).astype(np.uint8)


def box(size: int, top: int, bottom: int, left: int, right: int) -> np.ndarray:
    mask = np.zeros((size, size), bool)
    mask[top:bottom, left:right] = True
    return mask


def core_grain(recolour: ModuleType, pixels: np.ndarray, area: np.ndarray) -> float:
    return float(recolour.grain(pixels)[area].std())


def test_a_grainy_patch_comes_down_to_the_original(recolour: ModuleType) -> None:
    size = recolour.SIZE
    original = noisy(size, 3)
    patch = box(size, 600, 1400, 600, 1400)
    cleaned = np.where(patch[..., None], noisy(size, 12, 2), original)

    matched = recolour.match_grain(cleaned, original, [patch])

    core = box(size, 700, 1300, 700, 1300)
    surrounding = recolour.grain(original)[recolour.ring_outside(patch)].std()
    assert core_grain(recolour, matched, core) == pytest.approx(surrounding, rel=0.25)


def test_a_smooth_patch_comes_up_to_the_original(recolour: ModuleType) -> None:
    size = recolour.SIZE
    original = noisy(size, 6)
    patch = box(size, 600, 1400, 600, 1400)
    cleaned = np.where(patch[..., None], np.uint8(60), original)

    matched = recolour.match_grain(cleaned, original, [patch])

    core = box(size, 700, 1300, 700, 1300)
    surrounding = recolour.grain(original)[recolour.ring_outside(patch)].std()
    assert core_grain(recolour, matched, core) == pytest.approx(surrounding, rel=0.25)


def test_a_half_grainy_half_smooth_patch_evens_out(recolour: ModuleType) -> None:
    size = recolour.SIZE
    original = noisy(size, 6)
    patch = box(size, 600, 1400, 600, 1400)
    cleaned = original.copy()
    cleaned[600:1400, 600:1000] = noisy(size, 16, 2)[600:1400, 600:1000]
    cleaned[600:1400, 1000:1400] = 60

    matched = recolour.match_grain(cleaned, original, [patch])

    left = core_grain(recolour, matched, box(size, 700, 1300, 700, 950))
    right = core_grain(recolour, matched, box(size, 700, 1300, 1050, 1300))
    assert left == pytest.approx(right, rel=0.25)


def test_every_patch_is_matched(recolour: ModuleType) -> None:
    size = recolour.SIZE
    original = noisy(size, 3)
    patches = [box(size, 200, 700, 200, 700), box(size, 1200, 1700, 1200, 1700)]
    cleaned = original.copy()
    for patch in patches:
        cleaned = np.where(patch[..., None], noisy(size, 12, 2), cleaned)

    matched = recolour.match_grain(cleaned, original, patches)

    for area in (box(size, 300, 600, 300, 600), box(size, 1300, 1600, 1300, 1600)):
        assert core_grain(recolour, matched, area) < core_grain(recolour, cleaned, area) / 2


def test_pixels_outside_the_patch_and_in_its_holes_are_untouched(recolour: ModuleType) -> None:
    size = recolour.SIZE
    original = noisy(size, 3)
    patch = box(size, 600, 1400, 600, 1400)
    patch[900:1000, 900:1000] = False  # a kept hole, say a hand over the print
    cleaned = np.where(patch[..., None], noisy(size, 12, 2), original)

    matched = recolour.match_grain(cleaned, original, [patch])

    assert np.array_equal(matched[~patch], cleaned[~patch])


def test_a_busy_edge_in_the_ring_does_not_raise_the_target(recolour: ModuleType) -> None:
    size = recolour.SIZE
    original = noisy(size, 3)
    patch = box(size, 600, 1400, 600, 1400)
    ring = recolour.ring_outside(patch)
    original[ring & box(size, 0, size, 0, 620)] = noisy(size, 40, 3)[
        ring & box(size, 0, size, 0, 620)
    ]
    cleaned = np.where(patch[..., None], noisy(size, 12, 2), original)

    matched = recolour.match_grain(cleaned, original, [patch])

    core = box(size, 700, 1300, 700, 1300)
    assert core_grain(recolour, matched, core) < core_grain(recolour, cleaned, core) / 2
