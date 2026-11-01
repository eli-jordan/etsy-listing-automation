"""Summarize full-resolution comparisons without treating model maps as truth.

This is CPU-only. Use an external completed validate_marigold.py output. Produces
numeric disagreement, a local image gallery and 1:1 crops for manual inspection.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from etsy_listings.core.preparation.artifacts import Artifacts
from etsy_listings.core.render import MarigoldAppearance, MaterialLayer, render_marigold_scene
from etsy_listings.core.workspace import Workspace

VISIBLE = 0.5  # visibility above which a map pixel counts as shown


ARTWORKS = ["white", "saturated", "fine", "transparent", "real"]
ONE_TO_ONE = ["white", "fine", "real"]
GALLERY_HEAD = [
    "<!doctype html><meta charset=utf-8><title>Native Marigold comparison</title>",
    "<style>body{font:16px sans-serif;background:#222;color:white}"
    "section{display:flex;gap:16px}figure{margin:8px}img{width:45vw}a{color:#9df}</style>",
    "<h1>Native full-resolution shared versus independent</h1>"
    "<p>Click an image for its original 2048px file. "
    "Left shares Bay; right prepares this photo independently. "
    "Model agreement is not ground truth.</p>",
]


@dataclass(frozen=True)
class _Pair:
    """One colour's shared and independently prepared maps."""

    pack: str
    name: str
    shared: Any
    independent: Any
    visible: np.ndarray


def _map_distance(artifacts: Artifacts, pair: _Pair) -> np.ndarray:
    box = artifacts.saved_inputs(pair.name).placements[0].quad
    placement_width = (
        np.linalg.norm(np.array(box[1]) - box[0]) + np.linalg.norm(np.array(box[2]) - box[3])
    ) / 2
    return (
        np.linalg.norm(pair.shared.material - pair.independent.material, axis=-1)[pair.visible]
        * placement_width
    )


def _render_photographic(workspace: Workspace, pair: _Pair, output: Path) -> None:
    with Image.open(workspace.root / "mockup-templates" / pair.name / "scene.png") as source:
        base = np.array(source.convert("RGB"))
    white = np.full((512, 512, 4), 255, np.uint8)
    for mode, maps in [("shared", pair.shared), ("independent", pair.independent)]:
        image = render_marigold_scene(
            base,
            [MaterialLayer(white, maps)],
            appearance=MarigoldAppearance(lighting_source="photo"),
        )
        image.save(output / "renders" / f"{pair.name}-white-photographic-{mode}.png")


def _compare_artwork(pair: _Pair, artwork: str, paths: list[Path], output: Path) -> dict:
    with Image.open(paths[0]) as first, Image.open(paths[1]) as second:
        x, y = np.array(first), np.array(second)
        delta = np.abs(x.astype(np.int16) - y.astype(np.int16))[pair.visible]
        if artwork in ONE_TO_ONE:
            pair_image = Image.new("RGB", (1024, 512))
            rectangle = (720, 700, 1232, 1212) if pair.pack == "fence" else (720, 1100, 1232, 1612)
            pair_image.paste(first.crop(rectangle), (0, 0))
            pair_image.paste(second.crop(rectangle), (512, 0))
            pair_image.save(output / "renders" / f"{pair.name}-{artwork}-one-to-one.png")
    return {
        "artwork": artwork,
        "identical_bytes": paths[0].read_bytes() == paths[1].read_bytes(),
        "mean_rgb_code_difference": float(delta.mean()),
        "p95_rgb_code_difference": float(np.percentile(delta, 95)),
    }


def _gallery_section(name: str, artwork: str, paths: list[Path], output: Path) -> list[str]:
    section = [f"<h2>{name}, {artwork}</h2><section>"]
    for mode, path in zip(["Shared Bay", "Independent"], paths, strict=True):
        relative = path.relative_to(output).as_posix()
        section.append(
            f"<figure><figcaption>{mode}</figcaption>"
            f'<a href="{relative}"><img src="{relative}"></a></figure>'
        )
    section.append("</section>")
    return section


def _compare(
    workspace: Workspace, artifacts: Artifacts, pair: _Pair, output: Path, gallery: list[str]
) -> dict:
    distance = _map_distance(artifacts, pair)
    _render_photographic(workspace, pair, output)
    a, b = pair.shared, pair.independent
    comparison: dict = {
        "name": pair.name,
        "map_difference_photo_pixels": {
            "mean": float(distance.mean()),
            "p95": float(np.percentile(distance, 95)),
            "max": float(distance.max()),
        },
        "visibility_difference_pixels": int(
            np.count_nonzero((a.visibility > VISIBLE) != (b.visibility > VISIBLE))
        ),
        "artworks": [],
    }
    for artwork in ARTWORKS:
        paths = [
            output / "renders" / f"{pair.name}-{artwork}-{mode}.png"
            for mode in ["shared", "independent"]
        ]
        comparison["artworks"].append(_compare_artwork(pair, artwork, paths, output))
        gallery.extend(_gallery_section(pair.name, artwork, paths, output))
    return comparison


def run(output: Path) -> None:
    workspace = Workspace.discover(root_override=output / "workspace")
    report: dict = {"warning": "model disagreement, not physical accuracy", "comparisons": []}
    gallery = list(GALLERY_HEAD)
    artifacts = Artifacts(workspace)
    for pack in ["folded", "fence"]:
        reference = pack + "-bay"
        with artifacts.acquire(reference, artifacts.saved_inputs(reference)) as shared:
            a = shared.maps[None]
            for colour in ["bay", "ivory", "black"]:
                name = pack + "-" + colour
                with artifacts.acquire(name, artifacts.saved_inputs(name)) as independent:
                    b = independent.maps[None]
                    visible = (a.visibility > VISIBLE) & (b.visibility > VISIBLE)
                    pair = _Pair(pack, name, a, b, visible)
                    report["comparisons"].append(
                        _compare(workspace, artifacts, pair, output, gallery)
                    )
    (output / "comparison.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (output / "review.html").write_text("\n".join(gallery), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output)
