"""Numeric-only inference evidence validation; deliberately no runtime imports."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

MAX_PIXELS = 4096 * 4096
MAX_ARCHIVE_BYTES = 640 * 1024 * 1024
ROLES = ("normals", "lighting", "depth")


class PredictionError(ValueError):
    """Evidence cannot be trusted; retry preparation rather than using it."""


def cache_path(root: Path, relative: str, *, suffix: str) -> Path:
    """Reject native/Windows escapes even on a non-Windows test host."""
    if not relative or chr(92) in relative or ":" in relative:
        raise PredictionError("Expected a relative cache path")
    parts = relative.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise PredictionError("Unsafe relative cache path")
    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root.resolve()) or path.suffix != suffix:
        raise PredictionError("Cache path escapes root or has an unexpected file type")
    return path


def validate_prediction(array: NDArray[np.float32], *, role: str, size: tuple[int, int]) -> None:
    width, height = size
    expected = (3 if role == "lighting" else 1, height, width, 1 if role == "depth" else 3)
    if (
        role not in ROLES
        or width <= 0
        or height <= 0
        or max(width, height) > 4096
        or width * height > MAX_PIXELS
    ):
        raise PredictionError("Unsupported role or prediction dimensions")
    if array.dtype != np.dtype("float32") or array.shape != expected:
        raise PredictionError("Prediction dtype or shape does not match its declared role and size")
    if not np.isfinite(array).all():
        raise PredictionError("Prediction contains non-finite values")
    if role == "normals":
        if np.any(np.abs(array) > 1.01) or not np.allclose(
            np.linalg.norm(array, axis=-1), 1, atol=0.02
        ):
            raise PredictionError("Normals must be finite unit vectors")
    elif array.min() < 0 or array.max() > 1:
        raise PredictionError("Prediction values outside [0, 1]")


def read_prediction(
    path: Path, *, role: str, checksum: str, size: tuple[int, int]
) -> NDArray[np.float32]:
    """Validate ZIP bounds and NPY headers before allocating, with pickle disabled."""
    try:
        if path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise PredictionError("Prediction archive exceeds size limit")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != checksum:
                raise PredictionError("Prediction checksum mismatch")
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) != 1 or members[0].filename != "prediction.npy":
                raise PredictionError("Prediction archive has unexpected members")
            if members[0].file_size > MAX_ARCHIVE_BYTES:
                raise PredictionError("Prediction array exceeds size limit")
            with archive.open(members[0]) as stream:
                version = np.lib.format.read_magic(stream)
                if version == (1, 0):
                    shape, _, dtype = np.lib.format.read_array_header_1_0(stream)
                elif version == (2, 0):
                    shape, _, dtype = np.lib.format.read_array_header_2_0(stream)
                else:
                    raise PredictionError("Unsupported prediction NPY version")
            width, height = size
            if min(width, height) < 1 or max(width, height) > 4096:
                raise PredictionError("Unsupported prediction dimensions")
            expected = (3 if role == "lighting" else 1, height, width, 1 if role == "depth" else 3)
            if (
                dtype != np.dtype("float32")
                or shape != expected
                or max(width, height) > 4096
                or width * height > MAX_PIXELS
            ):
                raise PredictionError("Prediction header has unsafe dtype or shape")
        with np.load(path, allow_pickle=False) as arrays:
            array: NDArray[np.float32] = arrays["prediction"]
        validate_prediction(array, role=role, size=size)
        return array
    except (OSError, ValueError, zipfile.BadZipFile, EOFError) as exc:
        if isinstance(exc, PredictionError):
            raise
        raise PredictionError(f"Invalid prediction artifact: {exc}") from exc
