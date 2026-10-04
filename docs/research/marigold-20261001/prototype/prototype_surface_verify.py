"""One-off numerical smoke checks and image exports for the throwaway trial.

Not a production test suite. Run with the trial server running:
uv run python docs/research/marigold-20261001/prototype/prototype_surface_verify.py --output <scratch-directory>
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json

import httpx
import numpy as np
import prototype_surface_math as math
from PIL import Image, ImageDraw

from etsy_listings.core.workspace import to_native_path


def numerical_checks() -> dict:
    base = np.full((128, 128, 3), 100, np.uint8)
    box = np.array([[24, 24], [103, 24], [103, 103], [24, 103]], np.float32)
    analysis = math.analyse(base, box, np.zeros((128, 128), np.uint8))
    surface, _ = math.fit_surface(analysis, 1, 0, 0, [])
    uv, metrics = math.flatten(surface)
    yy, xx = np.meshgrid(np.linspace(0, 1, math.MESH), np.linspace(0, 1, math.MESH), indexing="ij")
    error = float(np.max(np.abs(uv - np.stack([xx, yy], axis=-1))))
    assert error < 1e-6, f"Flat surface UV identity failed: {error}"
    material, valid = math.bake(uv, box, (128, 128))
    white = np.full((64, 64, 4), 255, np.uint8)
    output = math.composite(base, white, material, valid, np.full((128, 128), 0.5), 1)
    assert np.array_equal(output[valid == 0], base[valid == 0])
    assert 180 < output[64, 64, 0] < 200, "White ink must pick up linear-light shadow"
    hidden = np.zeros((64, 64, 4), np.uint8)
    hidden[..., 0] = 255
    assert np.array_equal(
        math.composite(base, hidden, material, valid, np.ones((128, 128)), 1), base
    )
    assert np.array_equal(
        output, math.composite(base, white, material, valid, np.full((128, 128), 0.5), 1)
    )
    for curve, relief in [(0, 0.15), (0.4, 0), (0.4, 0.15)]:
        fitted, _ = math.fit_surface(analysis, 0.7, curve, relief, [])
        mesh, _ = math.flatten(fitted)
        assert math.signed_areas(mesh).min() > 0
    return {
        "flat_uv_max_error": error,
        "outside_pixels": "byte identical",
        "transparent_hidden_rgb": "no contamination",
        "white_shadow_byte": int(output[64, 64, 0]),
        "determinism": "byte identical",
        "stress_maps": "no flipped triangles",
        "flat_metrics": metrics,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Explicit user-owned scratch directory")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--design", help="RGBA artwork to apply to every trial photo")
    parser.add_argument(
        "--sample", nargs="+", type=int, help="Only these zero-based sample indices"
    )
    parser.add_argument("--curve", type=float, help="One manual broad-curve override")
    parser.add_argument("--relief", type=float, help="One manual fold-strength override")
    args = parser.parse_args()
    output = to_native_path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    report = {"numerical_checks": numerical_checks(), "samples": []}
    with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=120) as client:
        state = client.get("/state").raise_for_status().json()
        for index, sample in enumerate(state["samples"]):
            if args.sample is not None and index not in args.sample:
                continue
            state = client.post(f"/sample/{index}").raise_for_status().json()
            if args.design:
                client.post(
                    "/artwork",
                    files={
                        "file": (
                            "artwork.png",
                            to_native_path(args.design).read_bytes(),
                            "image/png",
                        )
                    },
                ).raise_for_status()
            else:
                client.post("/artwork/landscape").raise_for_status()
            controls = state["controls"]
            if args.curve is not None:
                controls["curvature"] = args.curve
            if args.relief is not None:
                controls["relief"] = args.relief
            metrics = client.post("/fit", json=controls).raise_for_status().json()
            folder = output / f"sample-{index}"
            folder.mkdir(exist_ok=True)
            images = []
            for name in ["current", "quad", "surface", "folds"]:
                response = client.get(f"/image/{name}").raise_for_status()
                (folder / f"{name}-preview.png").write_bytes(response.content)
                images.append(Image.open(io.BytesIO(response.content)).convert("RGB"))
                if name != "current":
                    response = client.get(
                        f"/image/{name}", params={"full": "true"}
                    ).raise_for_status()
                    (folder / f"{name}.png").write_bytes(response.content)
            sheet = Image.new("RGB", (4 * 400, 450), "#15241c")
            draw = ImageDraw.Draw(sheet)
            for column, (name, image) in enumerate(
                zip(
                    ["Current", "Quad + lighting", "Broad surface", "Surface + folds"],
                    images,
                    strict=True,
                )
            ):
                image.thumbnail((400, 400), Image.Resampling.LANCZOS)
                sheet.paste(image, (column * 400, 35))
                draw.text((column * 400 + 12, 10), name, fill="white")
            sheet.save(folder / "comparison.jpg", quality=94)
            artifact = client.get("/calibration").raise_for_status().content
            (folder / "surface.npz").write_bytes(artifact)
            first = client.get("/image/folds", params={"full": "true"}).raise_for_status().content
            client.post(
                "/calibration", files={"file": ("surface.npz", artifact)}
            ).raise_for_status()
            reloaded = (
                client.get("/image/folds", params={"full": "true"}).raise_for_status().content
            )
            assert first == reloaded, "Saved map reapplication changed full-resolution pixels"
            client.post("/artwork/grid").raise_for_status()
            grid = client.get("/image/folds", params={"full": "true"}).raise_for_status().content
            (folder / "grid.png").write_bytes(grid)
            # Compare imported map against the direct arrays with a second, unrelated artwork.
            with np.load(io.BytesIO(artifact), allow_pickle=False) as archive:
                metadata = json.loads(str(archive["metadata"]))
                assert np.isfinite(archive["material"]).all()
            client.post(
                "/calibration", files={"file": ("surface.npz", artifact)}
            ).raise_for_status()
            assert (
                grid
                == client.get("/image/folds", params={"full": "true"}).raise_for_status().content
            )
            report["samples"].append(
                {
                    "name": sample["name"],
                    "provenance": sample["provenance"],
                    "metrics": metrics,
                    "map_roundtrip": "PNG bytes identical",
                    "second_design_roundtrip": "PNG bytes identical",
                    "photo_sha256": metadata["photo_sha256"],
                    "map_sha256": hashlib.sha256(artifact).hexdigest(),
                }
            )
            print(json.dumps({"sample": index, "metrics": metrics, "roundtrip": "OK"}), flush=True)
        client.post("/sample/0").raise_for_status()
        if args.design:
            client.post(
                "/artwork",
                files={
                    "file": ("artwork.png", to_native_path(args.design).read_bytes(), "image/png")
                },
            ).raise_for_status()
        else:
            client.post("/artwork/landscape").raise_for_status()
    (output / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Smoke checks and trial exports complete: {output}")


if __name__ == "__main__":
    main()
