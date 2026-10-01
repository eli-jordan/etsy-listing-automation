"""THROWAWAY regression loop: a weak diagonal ripple and a deep edge fold.

Run: PYTHONPATH=src uv run --no-sync python scripts/debug_surface_features.py
Synthetic Lambertian surfaces isolate detection/fit attenuation; passing does
not establish physical depth accuracy for an unconstrained real photograph.
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np
import prototype_surface_math as math


def fixture(kind: str) -> tuple[math.Pixels, math.Float, math.Float]:
    yy, xx = np.meshgrid(np.linspace(0, 1, math.SIZE), np.linspace(0, 1, math.SIZE), indexing="ij")
    if kind == "gentle":
        across = (xx + yy - 1) / np.sqrt(2)
        height = 0.035 * np.exp(-0.5 * (across / 0.11) ** 2)
        region = (np.abs(across) < 0.12) & (xx > 0.15) & (xx < 0.85)
    else:
        across = xx - 0.06 + 0.5 * (yy - 0.75)
        height = (
            0.14 * np.exp(-0.5 * (across / 0.035) ** 2) * np.exp(-0.5 * ((yy - 0.75) / 0.16) ** 2)
        )
        region = (np.abs(across) < 0.065) & (yy > 0.55) & (yy < 0.9)
    dy, dx = np.gradient(height, 1 / (math.SIZE - 1))
    normal = np.stack([-dx, -dy, np.ones_like(xx)], axis=-1)
    normal /= np.linalg.norm(normal, axis=-1)[..., None]
    lamp = np.array([0.4, 0.5, 1])
    lamp /= np.linalg.norm(lamp)
    luminance = 0.07 + 0.18 * np.maximum(normal @ lamp, 0)
    photo = math.display(np.repeat(luminance[..., None], 3, axis=-1).astype(np.float32))
    return photo, height.astype(np.float32), region


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh", type=int, choices=[17, 33, 49], default=49)
    args = parser.parse_args()
    start = time.perf_counter()
    failures = []
    for kind in ["gentle", "deep"]:
        photo, truth, region = fixture(kind)
        edge = math.SIZE - 1
        box = np.array([[0, 0], [edge, 0], [edge, edge], [0, edge]], np.float32)
        analysis = math.analyse(photo, box, np.zeros((math.SIZE, math.SIZE), np.uint8))
        surface, _ = math.fit_surface(analysis, 1, 0, 0.045, [], args.mesh)
        uv, metrics = math.flatten(surface)
        coverage = float(np.mean(analysis.confidence[region] > 0.1))
        fitted = math.resize(surface[..., 2], (math.SIZE, math.SIZE))
        response = float(np.ptp(fitted[region]) / np.ptp(truth[region]))
        shift = float(metrics["max_material_shift"])
        print(
            json.dumps(
                {
                    "feature": kind,
                    "mesh": args.mesh,
                    "candidate_coverage": coverage,
                    "relief_response_ratio": response,
                    "uv_shift": shift,
                    "candidates": len(analysis.folds),
                    "flips": metrics["flipped_cells"],
                }
            )
        )
        if coverage < 0.35:
            failures.append(f"{kind}: detection erases most of the fold band ({coverage:.1%})")
        if kind == "deep" and response < 0.3:
            failures.append(
                f"deep: fit retains under 30% of known relief variation ({response:.1%})"
            )
        if kind == "deep" and shift < 0.005:
            failures.append(f"deep: material deformation is visually negligible ({shift:.2%})")
        assert math.signed_areas(uv).min() > 0
    if failures:
        raise AssertionError("; ".join(failures))
    print("PASS: weak diagonal and deep edge-fold response retained; no flipped cells")
    print(f"Two feature checks: {time.perf_counter() - start:.3f}s")


if __name__ == "__main__":
    main()
