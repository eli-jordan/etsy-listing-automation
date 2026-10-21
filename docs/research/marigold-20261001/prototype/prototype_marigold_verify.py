"""THROWAWAY numerical gates and isolated-server comparison/export gallery.

Synthetic expectations are analytical; they do not establish learned accuracy.
The batch changes server photo/artwork: point --url at an isolated instance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import httpx
import numpy as np
import prototype_marigold_math as math
import prototype_marigold_worker as worker
import prototype_surface_math as classical
from PIL import Image

from etsy_listings.core.workspace import to_native_path


def normals_from_slopes(dx: math.Float, dy: math.Float) -> math.Float:
    normals = np.stack([-dx, dy, np.ones_like(dx)], -1).astype(np.float32)
    return normals / np.linalg.norm(normals, axis=-1, keepdims=True)


def numerical_checks() -> dict:
    mesh = 49
    y, x = np.mgrid[:mesh, :mesh].astype(np.float32) / (mesh - 1)
    xy = np.stack([x, y], -1)
    confidence = np.ones((mesh, mesh), np.float32)
    ids = np.ones((mesh, mesh), np.int32)
    result = {}
    for name, z, dx, dy in [
        ("flat", np.zeros_like(x), np.zeros_like(x), np.zeros_like(x)),
        ("tilted", 0.3 * x + 0.2 * y, np.full_like(x, 0.3), np.full_like(y, 0.2)),
        (
            "cylinder",
            np.sqrt(0.7**2 - (x - 0.5) ** 2),
            -(x - 0.5) / np.sqrt(0.7**2 - (x - 0.5) ** 2),
            np.zeros_like(y),
        ),
        (
            "ripple",
            0.025 * np.sin(4 * np.pi * x),
            0.1 * np.pi * np.cos(4 * np.pi * x),
            np.zeros_like(y),
        ),
    ]:
        normals = normals_from_slopes(dx, dy)
        surface, metrics = math.integrate(xy, normals, confidence, ids)
        fitted = surface[..., 2] - surface[24, 24, 2]
        expected = z - z[24, 24]
        error = float(np.max(np.abs(fitted - expected)))
        assert error < 0.003, (name, "normal sign/scale/integration", error)
        uv, flat = math.flatten(surface, ids)
        assert flat["invalid_triangles"] == 0, (name, flat)
        if name in {"flat", "tilted"}:
            uv_error = float(np.max(np.abs(uv - xy)))
            assert uv_error < 0.004, (name, "planar mapping", uv_error)
        else:
            if name == "cylinder":
                arc = np.arcsin((x[0] - 0.5) / 0.7)
            else:
                dense = np.linspace(0, 1, 10001)
                derivative = 0.1 * np.pi * np.cos(4 * np.pi * dense)
                integral = np.cumsum(np.sqrt(1 + derivative**2))
                arc = np.interp(x[0], dense, integral)
            expected_u = (arc - arc[0]) / (arc[-1] - arc[0])
            uv_error = float(np.max(np.abs(uv[24, :, 0] - expected_u)))
            assert uv_error < 0.025, (name, "analytical arc-length mapping", uv_error)
        result[name] = {"height_max_error": error, "uv_max_error": uv_error, **flat, **metrics}
    # Depth is fitted in the same frame, not added: an affine transformed tilted
    # plane should recover the same height (up to an irrelevant constant).
    n = normals_from_slopes(np.full_like(x, 0.3), np.full_like(y, 0.2))
    depth = 1 - (0.3 * x + 0.2 * y) * 1.8
    surface, metrics = math.integrate(xy, n, confidence, ids, depth, confidence)
    assert metrics["depth"]["used"]
    assert abs(metrics["depth"]["scale"] - 1 / 1.8) < 0.005
    # Back-facing and grazing normals are flagged and cannot explode the fit.
    _, usable = math.slopes(np.broadcast_to(np.array([1, 0, 0.01], np.float32), (mesh, mesh, 3)))
    assert not usable.any()
    # Known two-patch overlap: preserve front ordering and a hidden material
    # interval of 0.12 rather than stretching both pieces into entire prints.
    size = (129, 129)
    box = np.array([[0, 0], [128, 0], [128, 128], [0, 128]], np.float32)
    patches = [
        {"points": [[64, 0], [128, 0], [128, 128], [64, 128]], "offset": [0.12, 0], "order": 1},
        {"points": [[90, 40], [110, 40], [110, 80], [90, 80]], "offset": [0.2, 0], "order": 2},
    ]
    full_ids = math.patch_labels(size, patches)
    grid = math.placement_grid(box, mesh)
    grid_ids = math.sample_labels(full_ids, grid)
    material, visible, labels = math.bake(xy, box, size, patches, grid_ids)
    assert abs((material[20, 65, 0] - material[20, 63, 0]) - (2 / 128 + 0.12)) < 0.0001
    assert labels[60, 100] == 3 and labels[20, 100] == 2
    assert abs(material[60, 100, 0] - (100 / 128 + 0.2)) < 0.0001
    result["overlap"] = {
        "hidden_interval": 0.12,
        "frontmost_patch": 3,
        "shared_coordinate_plane": True,
    }
    # A boundary directly between 1 and 3 must not invent label 2.
    discrete = np.tile(np.array([1, 1, 3, 3], np.int32), (4, 1))
    assert math.sample_labels(discrete, np.array([[[1.5, 1.5]]], np.float32))[0, 0] in {1, 3}
    step = np.zeros((4, 4, 2), np.float32)
    step[..., 0] = np.where(discrete == 1, 0.1, 0.9)
    preview, preview_ids = math.resize_material(step, discrete, (3, 3))
    assert np.allclose(preview[..., 0], np.where(preview_ids == 1, 0.1, 0.9))
    assert np.max(np.abs(math.patch_derivative(step, discrete, 1))) == 0
    # A hidden UV interval must not pick blurred mips along its two banks.
    yy, xx = np.mgrid[:64, :64].astype(np.float32)
    jump = np.stack([xx / 128, yy / 128], -1)
    jump[:, 32:, 0] += 0.25
    jump_ids = np.where(xx < 32, 1, 3).astype(np.int32)
    checker = np.full((128, 128, 4), 255, np.uint8)
    checker[::2, ::2, :3] = 0
    checker[1::2, 1::2, :3] = 0
    expected = math.sample(classical.premultiply(checker), jump * 127, cv2.BORDER_CONSTANT)
    filtered = math.filtered_sample(checker, jump, jump_ids)
    assert np.allclose(filtered[:, 31:33], expected[:, 31:33], atol=1e-6)
    result["patch_sampling"] = {
        "labels_remain_discrete": True,
        "preview_preserves_hidden_interval": True,
        "mip_derivatives_do_not_cross_patches": True,
    }
    anchored, metrics = math.flatten(
        np.stack([x, y, np.zeros_like(x)], -1), ids, [{"location": [0.5, 0.5], "uv": [0.62, 0.5]}]
    )
    assert np.max(np.abs(anchored[24, 24] - [0.62, 0.5])) < 1e-5
    assert metrics["invalid_triangles"] == 0 and metrics["final_frame_rms_strain"] > 0.02
    result["corrective_anchor"] = {
        "desired_u": 0.62,
        "actual_u": float(anchored[24, 24, 0]),
        "final_frame_rms_strain": metrics["final_frame_rms_strain"],
    }
    # Opaque white, half illumination: independent linear->sRGB worked value is
    # round(1.055*0.5**(1/2.4)-0.055)*255 = 188 (not dark garment multiplication).
    base = np.full((129, 129, 3), 20, np.uint8)
    art = np.full((129, 129, 4), 255, np.uint8)
    visibility = np.ones((129, 129), np.float32)
    visibility[:10] = 0
    gain = np.full((129, 129, 3), 0.5, np.float32)
    texture = np.ones((129, 129), np.float32)
    residual = np.zeros((129, 129, 3), np.float32)
    neutral, _ = classical.bake(xy, box, size)
    output = math.composite(base, art, neutral, visibility, gain, texture, residual)
    assert (output[64, 64] == 188).all()
    assert np.array_equal(output[:10], base[:10])
    # Transparent hidden RGB cannot leak, including antialiasing under compression.
    hidden = art.copy()
    hidden[:, :64, :3] = [255, 0, 255]
    hidden[:, :64, 3] = 0
    clean = hidden.copy()
    clean[:, :64, :3] = 0
    assert np.array_equal(
        math.composite(base, hidden, neutral, visibility, gain, texture, residual),
        math.composite(base, clean, neutral, visibility, gain, texture, residual),
    )
    photo_hash = hashlib.sha256(base.tobytes()).hexdigest()
    calibration = math.Calibration(
        neutral,
        visibility,
        labels,
        gain,
        texture,
        residual,
        {
            "format": "marigold-garment-v1",
            "photo_sha256": photo_hash,
            "size": list(size),
            "render_settings": {"texture": 0.25, "residual": 0},
        },
    )
    packed = calibration.dumps()
    loaded = math.Calibration.loads(packed, photo_hash, size)
    calibration.metadata["provenance"] = {"timestamp": "volatile", "path": "C:/irrelevant"}
    assert calibration.identity() == loaded.identity()
    assert np.array_equal(calibration.render(base, art), loaded.render(base, art))
    assert np.array_equal(calibration.render(base, hidden), loaded.render(base, hidden))
    try:
        math.Calibration.loads(packed, "different-photo", size)
    except ValueError:
        pass
    else:
        raise AssertionError("Different photo accepted")
    assert "torch" not in sys.modules
    result["compositor"] = {
        "half_lit_white_srgb": 188,
        "outside_pixels_identical": True,
        "hidden_rgb_isolated": True,
        "roundtrip_exact": True,
        "replacement_without_gpu": True,
    }
    # A/B/A setting replay must repoint the active file and preserve measurements.
    with tempfile.TemporaryDirectory(prefix="marigold-cache-check-") as temporary:
        directory = Path(temporary)
        for resolution in (768, 1024):
            metadata = {
                "settings": {"processing_resolution": resolution},
                "prediction_shape": [1, 2, 2, 3],
                "inference_seconds": 4.0,
            }
            np.savez_compressed(
                directory / f"normals-{resolution}.npz",
                prediction=np.zeros((1, 2, 2, 3), np.float32),
                metadata=np.array(json.dumps(metadata)),
            )
        for resolution in (768, 1024, 768):
            record = worker.activate_cached(
                directory / f"normals-{resolution}.npz",
                "normals",
                {"settings": {"processing_resolution": resolution}},
            )
            pointer = json.loads((directory / "normals.json").read_text())
            assert pointer["file"] == f"normals-{resolution}.npz"
            assert record["cached"] and record["inference_seconds"] == 4.0
    repository = Path(__file__).resolve().parents[4]
    for script, arguments in [
        ("worker", ["--jobs", "nonexistent.json"]),
        ("inputs", ["--root", str(repository)]),
        ("verify", []),
    ]:
        rejected = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name(f"prototype_marigold_{script}.py")),
                *arguments,
                "--output",
                "./unused/../trial-output",
            ],
            cwd=repository,
            capture_output=True,
            text=True,
            check=False,
        )
        assert rejected.returncode == 2 and "outside" in rejected.stderr, rejected.stderr
    result["cache_and_paths"] = {"settings_a_b_a": True, "relative_repo_outputs_rejected": True}
    return result


def evidence_gallery(cache: Path, output: Path) -> dict:
    """Inspect prediction quality on unwarped crops before making solver claims."""
    output.mkdir(parents=True, exist_ok=True)
    html = [
        "<!doctype html><meta charset=utf-8><title>Raw Marigold evidence</title>"
        "<style>body{font:14px system-ui;background:#151c18;color:#eee;padding:24px}"
        "section{display:flex;gap:12px}figure{margin:0;width:33%}img{width:100%}</style>"
        "<h1>Default vs 3-member / 10-step ensemble</h1>"
        "<p>Unwarped contextual crops. Upsampling does not recover fine wrinkles.</p>"
    ]
    records = {}
    for job in json.loads((cache / "jobs.json").read_text(encoding="utf-8")):
        directory = output / job["name"]
        directory.mkdir(exist_ok=True)
        with Image.open(job["photo"]) as photo:
            photo.convert("RGB").crop(tuple(job["crop"])).save(directory / "crop.png")
        html.append(f"<h2>{job['name']}</h2>")
        by_quality = {}
        for quality in ["default", "ensemble"]:
            by_quality[quality] = {}
            for role in ["normals", "lighting", "depth"]:
                pointer = json.loads((cache / quality / job["name"] / f"{role}.json").read_text())
                with np.load(
                    cache / quality / job["name"] / pointer["file"], allow_pickle=False
                ) as archive:
                    pred = archive["prediction"]
                    if role == "normals":
                        normals = pred[0]
                        normals /= np.maximum(np.linalg.norm(normals, axis=-1, keepdims=True), 1e-8)
                        by_quality[quality]["normals"] = normals
                        vis = np.rint((normals + 1) * 127.5).clip(0, 255).astype(np.uint8)
                        Image.fromarray(vis).save(directory / f"{quality}-normals.png")
                    if "uncertainty" in archive:
                        spread = archive["uncertainty"]
                        by_quality[quality][f"{role}_uncertainty_p95"] = float(
                            np.percentile(spread, 95)
                        )
                    by_quality[quality][f"{role}_seconds"] = pointer["inference_seconds"]
                    by_quality[quality][f"{role}_peak_mb"] = pointer["peak_allocated_bytes"] / 2**20
        dot = np.sum(
            by_quality["default"].pop("normals") * by_quality["ensemble"].pop("normals"), axis=-1
        )
        angle = np.degrees(np.arccos(np.clip(dot, -1, 1)))
        records[job["name"]] = {
            "mean_normal_change_degrees": float(angle.mean()),
            "p95_normal_change_degrees": float(np.percentile(angle, 95)),
            "settings": by_quality,
        }
        html.append("<section>")
        for file, label in [
            ("crop.png", "Original blank crop"),
            ("default-normals.png", "Default normals"),
            ("ensemble-normals.png", "Ensemble normals"),
        ]:
            html.append(
                f'<figure><img src="{job["name"]}/{file}"><figcaption>{label}</figcaption></figure>'
            )
        html.append("</section>")
    (output / "index.html").write_text("\n".join(html), encoding="utf-8")
    (output / "measurements.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    return records


def gallery(url: str, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(base_url=url, timeout=240)

    def request(method: str, path: str, **kwargs: object) -> httpx.Response:
        response = client.request(method, path, **kwargs)
        response.raise_for_status()
        return response

    initial = request("GET", "/state").json()
    records = []
    html = [
        "<!doctype html><meta charset=utf-8><title>Marigold trial evidence</title><style>"
        "body{font:14px system-ui;background:#151c18;color:#eee;padding:24px}"
        "img{max-width:100%;display:block}"
        "section{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}"
        "figure{margin:0}a{color:#bdf0cc}pre{white-space:pre-wrap}details{margin:20px 0}</style>"
        "<h1>THROWAWAY Marigold trial</h1><p>AI reconstructed worn blanks are stress tests, "
        "not ground truth. Method scores require user judgment. "
        "Default placement is fixed across comparisons.</p>"
    ]
    for index, sample in enumerate(initial["samples"]):
        state = request("POST", f"/sample/{index}").json()
        name = sample["name"]
        directory = output / name
        directory.mkdir(exist_ok=True)
        metrics = request("POST", "/fit", json=state["controls"]).json()
        (directory / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        (directory / "controls.json").write_text(
            json.dumps(state["controls"], indent=2), encoding="utf-8"
        )
        photo = request("GET", "/photo").content
        (directory / "blank-preview.png").write_bytes(photo)
        html.append(
            f"<h2>{name}</h2><p>{sample['provenance']}</p>"
            "<details><summary>Raw field inspection</summary><section>"
        )
        for diagnostic in initial["diagnostics"]:
            data = request("GET", f"/image/{diagnostic}").content
            (directory / f"{diagnostic}.png").write_bytes(data)
            html.append(
                f'<figure><img loading="lazy" src="{name}/{diagnostic}.png">'
                f"<figcaption>{diagnostic}</figcaption></figure>"
            )
        html.append("</section></details>")
        saved_map = request("GET", "/calibration").content
        (directory / "marigold-garment-v1.npz").write_bytes(saved_map)
        for artwork in ["custom", "grid", "landscape", "white", "colour", "text", "edges"]:
            request("POST", f"/artwork/{artwork}")
            methods = list(initial["methods"]) if artwork in {"custom", "grid"} else ["selected"]
            html.append(
                f"<details {'open' if artwork == 'custom' else ''}>"
                f"<summary>{artwork}</summary><section>"
            )
            for method in methods:
                data = request("GET", f"/image/{method}?full=true").content
                filename = f"{artwork}-{method}.png"
                (directory / filename).write_bytes(data)
                html.append(
                    f'<figure><a href="{name}/{filename}">'
                    f'<img loading="lazy" src="{name}/{filename}"></a>'
                    f"<figcaption>{initial['methods'][method]}</figcaption></figure>"
                )
            html.append("</section></details>")
            before = request("GET", "/image/selected?full=true").content
            request("POST", "/calibration", files={"file": ("map.npz", saved_map)})
            after = request("GET", "/image/selected?full=true").content
            assert before == after, (name, artwork, "saved-map byte roundtrip")
            # Keep the imported selected calibration while changing artwork.
            if artwork != "edges":
                request("POST", "/fit", json=state["controls"])
        # Foreign photo rejection through the public server boundary.
        other = (index + 1) % len(initial["samples"])
        request("POST", f"/sample/{other}")
        rejection = client.post("/calibration", files={"file": ("map.npz", saved_map)})
        assert rejection.status_code == 400
        records.append(
            {
                "name": name,
                "provenance": sample["provenance"],
                "metrics": metrics,
                "roundtrip_artworks": 7,
                "photo_mismatch_rejected": True,
                "active_user_effort": "unmeasured; presets reused, no user trial",
                "score": {
                    "placement": None,
                    "crease_alignment": None,
                    "deep_folds": None,
                    "illumination": None,
                    "texture_edges": None,
                    "occlusion": None,
                    "overall": None,
                },
            }
        )
        print(f"Verified {name}: 7 exact artifact roundtrips and mismatch rejection", flush=True)
    html.append(
        "<h2>Blind review</h2><p>Randomized and relabelled variants: "
        "use blind-review.html, reveal keys in blind-key.json after scoring.</p>"
    )
    (output / "index.html").write_text("\n".join(html), encoding="utf-8")
    blind = [
        "<!doctype html><meta charset=utf-8><title>Blind review</title><style>"
        "body{font:14px system-ui;background:#151c18;color:#eee;padding:24px}"
        "section{display:flex;gap:12px}figure{width:33%;margin:0}img{width:100%}</style>"
        "<h1>Blind overall review</h1>"
    ]
    keys = {}
    randomizer = random.Random(2026)
    for record in records:
        name = record["name"]
        methods = ["production", "classical", "selected"]
        randomizer.shuffle(methods)
        blind.append(f"<h2>{name}</h2><section>")
        keys[name] = dict(zip("ABC", methods, strict=True))
        for letter, method in zip("ABC", methods, strict=True):
            # Neutral filenames avoid method disclosure in the image URL.
            filename = f"blind-{letter}.png"
            (output / name / filename).write_bytes(
                (output / name / f"custom-{method}.png").read_bytes()
            )
            blind.append(
                f'<figure><a href="{name}/{filename}"><img src="{name}/{filename}"></a>'
                f"<figcaption>{letter}</figcaption></figure>"
            )
        blind.append("</section>")
    (output / "blind-review.html").write_text("\n".join(blind), encoding="utf-8")
    (output / "blind-key.json").write_text(json.dumps(keys, indent=2), encoding="utf-8")
    report = {
        "cases": records,
        "genuine_worn_blank": "not available; held-out validation remains outstanding",
    }
    (output / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    client.close()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url", help="Isolated prototype server (mutates its current photo/artwork)"
    )
    parser.add_argument("--output", help="Gallery path outside repository; native or Cygwin")
    parser.add_argument("--cache", help="Worker cache to export a raw default/ensemble comparison")
    args = parser.parse_args()
    output = to_native_path(args.output).resolve() if args.output else None
    if output and output.is_relative_to(Path(__file__).resolve().parents[4]):
        parser.error("Keep photo exports outside repository")
    result = {"numerical": numerical_checks()}
    print(json.dumps(result, indent=2), flush=True)
    if args.url:
        if not args.output:
            parser.error("--url requires --output")
        result["gallery"] = gallery(args.url, output)
    if args.cache:
        if not args.output:
            parser.error("--cache requires --output")
        result["evidence"] = evidence_gallery(to_native_path(args.cache), output / "evidence")
    if output:
        output.mkdir(parents=True, exist_ok=True)
        (output / "numerical.json").write_text(
            json.dumps(result["numerical"], indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
