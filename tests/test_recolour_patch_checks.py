"""The create-mockup-template-cc1717 skill's `patch_checks` and `patch_problems`: whether a
clean-up patch's grain matches the fabric around it."""

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
    grain = rng.normal(0, sigma, (size, size, 1))
    return np.clip(120 + grain, 0, 255).repeat(3, axis=2).astype(np.uint8)


def box(size: int) -> np.ndarray:
    mask = np.zeros((size, size), bool)
    mask[600:1400, 600:1400] = True
    return mask


def grain_problems(
    recolour: ModuleType, original: np.ndarray, cleaned: np.ndarray, patch: np.ndarray
) -> list[str]:
    checks = recolour.patch_checks(original, cleaned, cleaned, patch)
    return [problem for problem in recolour.patch_problems(0, checks) if "x the surr" in problem]


def test_matching_grain_passes(recolour: ModuleType) -> None:
    size = recolour.SIZE
    original = noisy(size, 6)
    patch = box(size)
    cleaned = np.where(patch[..., None], noisy(size, 6, 2), original)

    assert not grain_problems(recolour, original, cleaned, patch)


def test_hard_edges_beside_the_patch_do_not_fail_it(recolour: ModuleType) -> None:
    size = recolour.SIZE
    original = noisy(size, 2)
    for row in range(1405, 1430, 6):
        original[row : row + 3, 500:1500] = 255
    patch = box(size)
    cleaned = np.where(patch[..., None], noisy(size, 2, 2), original)

    assert not grain_problems(recolour, original, cleaned, patch)


def test_a_smooth_patch_fails(recolour: ModuleType) -> None:
    size = recolour.SIZE
    original = noisy(size, 6)
    patch = box(size)
    cleaned = np.where(patch[..., None], np.uint8(120), original)

    assert grain_problems(recolour, original, cleaned, patch)


def test_a_too_grainy_patch_fails(recolour: ModuleType) -> None:
    size = recolour.SIZE
    original = noisy(size, 3)
    patch = box(size)
    cleaned = np.where(patch[..., None], noisy(size, 12, 2), original)

    assert grain_problems(recolour, original, cleaned, patch)
