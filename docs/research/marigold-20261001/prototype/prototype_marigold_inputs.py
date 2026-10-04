"""THROWAWAY shared trial inputs and inference crop manifest (ADR-0013 path accessors)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from etsy_listings.core.workspace import Workspace, to_native_path


def arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", required=True)
    parser.add_argument("--template", default="cc1717-hanging-on-fence")
    parser.add_argument("--colour", default="pepper")
    parser.add_argument("--samples")
    parser.add_argument(
        "--holdout-colour", help="Additional genuine blank, evaluated with frozen defaults"
    )
    parser.add_argument("--output", required=True, help="Experimental cache outside repository")


def samples(args: argparse.Namespace) -> list[dict]:
    workspace = Workspace.discover(root_override=to_native_path(args.root))
    template = workspace.load_template_config(args.template)
    cfg = (
        template.render_config_for(template.placements[0])
        if template.kind == "multiple"
        else template.render_config()
    )
    photo = workspace.scene_photo(
        args.template, args.colour if template.kind == "colour-matrix" else None
    ).path
    result = [
        {
            "name": "fence",
            "path": str(photo),
            "provenance": "Genuine blank photograph",
            "config": cfg,
            "box": [[p.x, p.y] for p in cfg.bounding_box],
        }
    ]
    if args.samples:
        for original in json.loads(to_native_path(args.samples).read_text(encoding="utf-8")):
            sample = dict(original)
            path = to_native_path(sample["path"])
            with Image.open(path) as image:
                w, h = image.size
            sample["path"] = str(path)
            sample["name"] = path.stem.split("-")[0]
            sample["box"] = [[x * w, y * h] for x, y in sample["box"]]
            for stroke in sample.get("strokes", []):
                stroke["points"] = [[x * w, y * h] for x, y in stroke["points"]]
            result.append(sample)
    if args.holdout_colour:
        if template.kind != "colour-matrix":
            raise ValueError("--holdout-colour needs a colour-matrix template")
        held_out = workspace.scene_photo(args.template, args.holdout_colour).path
        result.append(
            {
                "name": f"holdout-{args.holdout_colour}",
                "path": str(held_out),
                "provenance": "Additional genuine blank; same photo setup, frozen defaults",
                "config": cfg,
                "box": [[p.x, p.y] for p in cfg.bounding_box],
            }
        )
    return result


def jobs(inputs: list[dict]) -> list[dict]:
    result = []
    for sample in inputs:
        with Image.open(sample["path"]) as image:
            w, h = image.size
        box = np.asarray(sample["box"])
        lo, hi = box.min(axis=0), box.max(axis=0)
        margin = (hi - lo) * 0.4
        crop = [
            max(0, int(lo[0] - margin[0])),
            max(0, int(lo[1] - margin[1])),
            min(w, int(hi[0] + margin[0]) + 1),
            min(h, int(hi[1] + margin[1]) + 1),
        ]
        result.append(
            {"name": sample["name"], "photo": sample["path"], "crop": crop, "size": [w, h]}
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    arguments(parser)
    args = parser.parse_args()
    output = to_native_path(args.output).resolve()
    if output.is_relative_to(Path(__file__).resolve().parents[4]):
        parser.error("Keep photos, inference caches and exports outside the repository")
    output.mkdir(parents=True, exist_ok=True)
    manifest = jobs(samples(args))
    (output / "jobs.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
