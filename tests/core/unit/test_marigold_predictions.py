import hashlib

import numpy as np
import pytest

from etsy_listings.core.preparation.predictions import PredictionError, read_prediction


def test_validated_prediction_requires_safe_numeric_shape_and_checksum(tmp_path):
    path = tmp_path / "depth.npz"
    np.savez_compressed(path, prediction=np.full((1, 8, 12, 1), 0.5, dtype=np.float32))
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    result = read_prediction(path, role="depth", checksum=checksum, size=(12, 8))
    assert result.shape == (1, 8, 12, 1)
    with pytest.raises(PredictionError, match="checksum"):
        read_prediction(path, role="depth", checksum="0" * 64, size=(12, 8))


def test_prediction_dimension_cap_applies_to_each_axis_before_allocation(tmp_path):
    path = tmp_path / "wide.npz"
    np.savez_compressed(path, prediction=np.full((1, 1, 8192, 1), 0.5, dtype=np.float32))
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(PredictionError, match="dimension"):
        read_prediction(path, role="depth", checksum=checksum, size=(8192, 1))


@pytest.mark.parametrize(
    "array,reason",
    [
        (np.array([object()], dtype=object), "dtype"),
        (np.full((1, 8, 12, 1), np.nan, dtype=np.float32), "non-finite"),
        (np.full((1, 8, 12, 1), 2, dtype=np.float32), "outside"),
        (np.zeros((1, 8, 12, 1), dtype=np.float64), "dtype"),
    ],
)
def test_unsafe_numeric_artifacts_are_refused(tmp_path, array, reason):
    path = tmp_path / "unsafe.npz"
    np.savez_compressed(path, prediction=array)
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(PredictionError, match=reason):
        read_prediction(path, role="depth", checksum=checksum, size=(12, 8))


@pytest.mark.parametrize(
    "relative",
    ["../outside.png", "/outside.png", "C:/outside.png", "bad//crop.png", "bad/crop.jpg"],
)
def test_cache_paths_refuse_escapes_and_unexpected_files(tmp_path, relative):
    from etsy_listings.core.preparation.predictions import cache_path

    with pytest.raises(PredictionError):
        cache_path(tmp_path, relative, suffix=".png")


def test_prediction_loading_imports_no_model_runtime(tmp_path):
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from etsy_listings.core.preparation.predictions import read_prediction; "
            "from etsy_listings.core.preparation.runtime import Runtime; "
            'assert "torch" not in sys.modules; assert "diffusers" not in sys.modules',
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
