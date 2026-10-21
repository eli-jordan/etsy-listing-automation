"""Summarize full-resolution comparisons without treating model maps as truth.

This is CPU-only. Use an external completed validate_marigold.py output. Produces
numeric disagreement, a local image gallery and 1:1 crops for manual inspection.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from etsy_listings.core.preparation.artifacts import Artifacts
from etsy_listings.core.render import MarigoldAppearance, MaterialLayer, render_marigold_scene
from etsy_listings.core.workspace import Workspace


def run(output: Path) -> None:
    workspace = Workspace.discover(root_override=output / "workspace")
    report: dict = {"warning": "model disagreement, not physical accuracy", "comparisons": []}
    gallery = [
        "<!doctype html><meta charset=utf-8><title>Native Marigold comparison</title>",
        "<style>body{font:16px sans-serif;background:#222;color:white}"
        "section{display:flex;gap:16px}figure{margin:8px}img{width:45vw}a{color:#9df}</style>",
        "<h1>Native full-resolution shared versus independent</h1>"
        "<p>Click an image for its original 2048px file. "
        "Left shares Bay; right prepares this photo independently. "
        "Model agreement is not ground truth.</p>",
    ]
    artifacts = Artifacts(workspace)
    for pack in ["folded", "fence"]:
        reference = pack + "-bay"
        with artifacts.acquire(reference, artifacts.saved_inputs(reference)) as shared:
            a = shared.maps[None]
            for colour in ["bay", "ivory", "black"]:
                name = pack + "-" + colour
                with artifacts.acquire(name, artifacts.saved_inputs(name)) as independent:
                    b = independent.maps[None]
                    visible = (a.visibility > 0.5) & (b.visibility > 0.5)
                    box = artifacts.saved_inputs(name).placements[0].quad
                    placement_width = (
                        np.linalg.norm(np.array(box[1]) - box[0])
                        + np.linalg.norm(np.array(box[2]) - box[3])
                    ) / 2
                    distance = (
                        np.linalg.norm(a.material - b.material, axis=-1)[visible] * placement_width
                    )
                    with Image.open(
                        workspace.root / "mockup-templates" / name / "scene.png"
                    ) as source:
                        base = np.array(source.convert("RGB"))
                    white = np.full((512, 512, 4), 255, np.uint8)
                    for mode, maps in [("shared", a), ("independent", b)]:
                        image = render_marigold_scene(
                            base,
                            [MaterialLayer(white, maps)],
                            appearance=MarigoldAppearance(lighting_source="photo"),
                        )
                        image.save(output / "renders" / f"{name}-white-photographic-{mode}.png")
                    comparison = {
                        "name": name,
                        "map_difference_photo_pixels": {
                            "mean": float(distance.mean()),
                            "p95": float(np.percentile(distance, 95)),
                            "max": float(distance.max()),
                        },
                        "visibility_difference_pixels": int(
                            np.count_nonzero((a.visibility > 0.5) != (b.visibility > 0.5))
                        ),
                        "artworks": [],
                    }
                    for artwork in ["white", "saturated", "fine", "transparent", "real"]:
                        paths = [
                            output / "renders" / f"{name}-{artwork}-{mode}.png"
                            for mode in ["shared", "independent"]
                        ]
                        with Image.open(paths[0]) as first, Image.open(paths[1]) as second:
                            x, y = np.array(first), np.array(second)
                            delta = np.abs(x.astype(np.int16) - y.astype(np.int16))[visible]
                            comparison["artworks"].append(
                                {
                                    "artwork": artwork,
                                    "identical_bytes": paths[0].read_bytes()
                                    == paths[1].read_bytes(),
                                    "mean_rgb_code_difference": float(delta.mean()),
                                    "p95_rgb_code_difference": float(np.percentile(delta, 95)),
                                }
                            )
                            if artwork in ["white", "fine", "real"]:
                                pair = Image.new("RGB", (1024, 512))
                                rectangle = (
                                    (720, 700, 1232, 1212)
                                    if pack == "fence"
                                    else (720, 1100, 1232, 1612)
                                )
                                pair.paste(first.crop(rectangle), (0, 0))
                                pair.paste(second.crop(rectangle), (512, 0))
                                pair.save(output / "renders" / f"{name}-{artwork}-one-to-one.png")
                        gallery.append(f"<h2>{name}, {artwork}</h2><section>")
                        for mode, path in zip(["Shared Bay", "Independent"], paths, strict=True):
                            relative = path.relative_to(output).as_posix()
                            gallery.append(
                                f"<figure><figcaption>{mode}</figcaption>"
                                f'<a href="{relative}"><img src="{relative}"></a></figure>'
                            )
                        gallery.append("</section>")
                    report["comparisons"].append(comparison)
    (output / "comparison.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (output / "review.html").write_text("\n".join(gallery), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output)
