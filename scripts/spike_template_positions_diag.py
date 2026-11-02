"""Padding diagnostic for the Marigold padded-fit spike (plan PR 1, P1/P2).

How does option A's misregistration at the template's own box grow with the
padding, and how much of it is a single global affine? For each template and
four sets of limits (none, tiny, half the defaults, the defaults) it fits the
padded quad, applies the identity pose as a UV affine, and compares the maps
with a direct fit of the template box. It reports the artwork shift in photo
pixels, the shift left after removing the best-fit global affine between the
two UV fields, and the padded quad's garment cover. The "zero" row is the
correctness check: with no padding, option A must reproduce the direct fit.

Run after ``spike_template_positions.py`` has stored the evidence::

    uv run python scripts/spike_template_positions_diag.py --workspace <throwaway> --out <dir>

Writes ``<out>/diagnostic.json``. Research only, like the harness it reuses.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

sys.path.insert(0, str(Path(__file__).resolve().parent))

import spike_template_positions as spike

from etsy_listings.core.render.material import (
    MaterialMaps,
)

LIMITS = (
    ("zero", spike.Limits(1.0, 1.0, 0.0, 0.0)),
    ("tiny", spike.Limits(0.98, 1.02, 0.01, 2.0)),
    ("half", spike.Limits(0.90, 1.05, 0.05, 7.5)),
    ("default", spike.DEFAULT_LIMITS),
)
PERCENTILE = 99


def full_frame(maps: MaterialMaps) -> tuple[NDArray[np.float32], NDArray[np.bool_]]:
    width, height = maps.size
    material = np.zeros((height, width, 2), np.float32)
    visible = np.zeros((height, width), bool)
    left, top, right, bottom = maps.extent
    material[top:bottom, left:right] = maps.material
    visible[top:bottom, left:right] = maps.visibility > 0
    return material, visible


def after_global_affine(
    reference: MaterialMaps, candidate: MaterialMaps, size: tuple[float, float]
) -> float:
    """99th-percentile shift in photo pixels once the best least-squares
    affine from the candidate's UV to the reference's is removed."""
    first, first_visible = full_frame(reference)
    second, second_visible = full_frame(candidate)
    both = first_visible & second_visible
    design = np.c_[second[both], np.ones(int(both.sum()))]
    target = first[both]
    affine = np.linalg.lstsq(design, target, rcond=None)[0]
    residual = np.linalg.norm((design @ affine - target) * np.array(size), axis=1)
    return float(np.percentile(residual, PERCENTILE))


def diagnose(workspace: Path, name: str) -> dict[str, dict[str, float]]:
    template = spike.load_template(workspace, name)
    frame = spike.BoxFrame.of(template.box)
    evidence = spike.evidence_for(
        template,
        frame.padded_quad(spike.DEFAULT_LIMITS),
        workspace / ".cache" / "spike-evidence",
        {},
    )
    direct = spike.prepare(template.base, spike.Placement(template.box, template.mask), evidence)
    size = (frame.width, frame.height)
    rows = {}
    for label, limits in LIMITS:
        quad = frame.padded_quad(limits)
        padded = spike.prepare(template.base, spike.Placement(quad, template.mask), evidence)
        option_a = spike.apply_position(
            padded.maps, spike.uv_affine(frame, limits, spike.Pose("identity")), renormalise=False
        )
        shift = spike.displacement(direct.maps, option_a, size)
        rows[label] = {
            "mean_px": shift["mean_px"],
            "p99_px": shift["p99_px"],
            "after_global_affine_p99_px": after_global_affine(direct.maps, option_a, size),
            "padded_quad_garment_cover": spike.garment_cover(template.mask, quad),
        }
        print(
            f"{name:34s} {label:8s} shift p99 {shift['p99_px']:6.2f}px "
            f"after affine {rows[label]['after_global_affine_p99_px']:6.2f}px "
            f"cover {rows[label]['padded_quad_garment_cover']:.3f}",
            flush=True,
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    results = {
        "limits": {label: limits.__dict__ for label, limits in LIMITS},
        "templates": {name: diagnose(args.workspace, name) for name in spike.TEMPLATES},
    }
    path = args.out / "diagnostic.json"
    path.write_text(json.dumps(results, indent=2))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
