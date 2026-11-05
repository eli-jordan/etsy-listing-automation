"""The create-mockup-template-cc1717 skill's `edited_patches`: which of the generator's
changes a clean-up keeps, for a print with parts close to the fabric's colour."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import cv2
import numpy as np
import pytest

SCRIPT = Path(__file__).parents[1] / ".claude/skills/create-mockup-template-cc1717/recolour.py"
FABRIC = (196, 24, 50)
WHITE_PRINT = (250, 250, 250)
# Under CLEAN_CHANGE on every channel against FABRIC, and close to its lightness.
FAINT_PRINT = (214, 44, 28)
PRINT_BOX = (800, 1200, 800, 1200)  # top, bottom, left, right


@pytest.fixture(scope="module")
def recolour() -> ModuleType:
    spec = importlib.util.spec_from_file_location("recolour", SCRIPT)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["recolour"] = module
    spec.loader.exec_module(module)
    return module


def fabric(size: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    grain = rng.normal(0, 2, (size, size, 1))
    return np.clip(np.array(FABRIC, np.float32) + grain, 0, 255).astype(np.uint8)


def with_print(pixels: np.ndarray) -> np.ndarray:
    """Fine stripes, because a real print is mostly edges."""
    top, bottom, left, right = PRINT_BOX
    printed = pixels.copy()
    for row in range(top, bottom, 24):
        printed[row : row + 12, left:right] = WHITE_PRINT
    return printed


def bulb(size: int, centre: tuple[int, int]) -> np.ndarray:
    mask = np.zeros((size, size), np.uint8)
    cv2.ellipse(mask, centre, (20, 30), 0, 0, 360, 1, -1)
    return mask > 0


def test_a_faint_print_item_beyond_the_patch_is_removed(recolour: ModuleType) -> None:
    size = recolour.SIZE
    item = bulb(size, (1000, 1290))
    original = with_print(fabric(size, 1))
    original[item] = FAINT_PRINT

    patches = recolour.edited_patches(original, fabric(size, 2))

    assert len(patches) == 1
    assert patches[0][item].all()


def test_a_redrawn_faint_item_stays_out_of_the_patch(recolour: ModuleType) -> None:
    size = recolour.SIZE
    item = bulb(size, (1000, 1290))
    redrawn = bulb(size, (1006, 1294))
    original = with_print(fabric(size, 1))
    original[item] = FAINT_PRINT
    generated = fabric(size, 2)
    generated[redrawn] = FAINT_PRINT

    patches = recolour.edited_patches(original, generated)

    assert len(patches) == 1
    assert not patches[0][item].all()


def test_a_faint_item_far_from_the_patch_is_left_alone(recolour: ModuleType) -> None:
    size = recolour.SIZE
    item = bulb(size, (1000, 1700))
    original = with_print(fabric(size, 1))
    original[item] = FAINT_PRINT

    patches = recolour.edited_patches(original, fabric(size, 2))

    assert len(patches) == 1
    assert not patches[0][item].any()


def test_a_faint_item_does_not_extend_the_reach_of_the_patch(recolour: ModuleType) -> None:
    size = recolour.SIZE
    near = bulb(size, (1000, 1290))
    beyond = bulb(size, (1000, 1395))
    original = with_print(fabric(size, 1))
    original[near | beyond] = FAINT_PRINT

    patches = recolour.edited_patches(original, fabric(size, 2))

    assert len(patches) == 1
    assert patches[0][near].all()
    assert not patches[0][beyond].any()
