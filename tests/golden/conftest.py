"""Shared golden-comparison fixture for both golden layers (per-pass and e2e).

A fixture rather than an importable helper module -- ``tests/`` isn't a
package (no ``__init__.py``), which is deliberate so ``tests/unit``,
``tests/behaviour`` etc. stay simple flat test directories; a fixture avoids
needing cross-directory imports to reach it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

GoldenComparator = Callable[[Image.Image, Path], None]


@pytest.fixture
def assert_matches_golden(update_goldens: bool) -> GoldenComparator:
    def _compare(actual: Image.Image, golden_path: Path, *, tolerance: int = 3) -> None:
        if update_goldens or not golden_path.is_file():
            golden_path.parent.mkdir(parents=True, exist_ok=True)
            actual.save(golden_path, format="PNG", optimize=False, compress_level=6, pnginfo=None)
            if not update_goldens:
                pytest.fail(
                    f"no golden at {golden_path} -- wrote one from this run. "
                    f"Review it, then re-run without --update-goldens."
                )
            return

        golden = Image.open(golden_path).convert(actual.mode)
        actual_arr = np.asarray(actual).astype(np.int16)
        golden_arr = np.asarray(golden).astype(np.int16)

        if actual_arr.shape != golden_arr.shape:
            pytest.fail(
                f"{golden_path.name}: shape {actual_arr.shape} does not match "
                f"golden shape {golden_arr.shape}"
            )

        diff = np.abs(actual_arr - golden_arr)
        per_pixel_max = diff.max(axis=-1) if diff.ndim == 3 else diff
        mismatched = int(np.sum(per_pixel_max > tolerance))
        if mismatched:
            total = per_pixel_max.size
            pytest.fail(
                f"{golden_path.name}: {mismatched}/{total} pixels "
                f"({100 * mismatched / total:.2f}%) differ from the golden by "
                f"more than tolerance {tolerance} (max observed diff: "
                f"{int(diff.max())}). Run with --update-goldens and review the "
                f"diff if this is an intended change."
            )

    return _compare
