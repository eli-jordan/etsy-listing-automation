"""THROWAWAY native Windows inference worker; no production imports.

Install scripts/prototype_marigold_requirements.txt into a separate environment.
Jobs contain photo, crop (original pixel edges), name. Cache records include every
checkpoint revision and inference setting; changing artwork never calls this file.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
import os
import platform
import time
from pathlib import Path

import numpy as np
from PIL import Image

MODELS = {
    "normals": (
        "prs-eth/marigold-normals-v1-1",
        "MarigoldNormalsPipeline",
        "09cfdd258cb281fa006cf1afcd2284376d16687d",
    ),
    "lighting": (
        "prs-eth/marigold-iid-lighting-v1-1",
        "MarigoldIntrinsicsPipeline",
        "08c3930bb641abf786ba44ce92547507ebefbc16",
    ),
    "depth": (
        "prs-eth/marigold-depth-v1-1",
        "MarigoldDepthPipeline",
        "9571e7123e258cf052b4e54241f17971c290e9a8",
    ),
}


def activate_cached(filename: Path, role: str, identity: dict) -> dict:
    """Select this exact archive again, even after a run with other settings."""
    with np.load(filename, allow_pickle=False) as archive:
        metadata = json.loads(str(archive["metadata"]))
        if any(metadata.get(k) != v for k, v in identity.items()):
            raise ValueError("Cached prediction identity does not match requested run")
        if list(archive["prediction"].shape) != metadata["prediction_shape"]:
            raise ValueError("Cached prediction shape does not match metadata")
    (filename.parent / f"{role}.json").write_text(
        json.dumps({"file": filename.name, **metadata}, indent=2), encoding="utf-8"
    )
    return {**metadata, "cached": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", required=True, help="Native path to JSON jobs")
    parser.add_argument("--output", required=True, help="Native path outside the repo")
    parser.add_argument("--quality", choices=["default", "ensemble"], default="default")
    parser.add_argument("--resolution", type=int, default=768)
    parser.add_argument("--smoke", action="store_true", help="Run first photo twice per model")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("Keep model weights and photo predictions outside repository")
    output.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(output / "weights"))
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    import diffusers
    import torch
    from huggingface_hub import HfApi

    if platform.system() != "Windows" or not torch.cuda.is_available():
        raise RuntimeError("This worker requires native Windows with working PyTorch CUDA.")
    versions = {
        package: importlib.metadata.version(package)
        for package in [
            "torch",
            "diffusers",
            "transformers",
            "accelerate",
            "huggingface-hub",
            "numpy",
            "pillow",
            "safetensors",
            "scipy",
        ]
    }
    device = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "gpu": torch.cuda.get_device_name(),
        "cuda": torch.version.cuda,
        "memory_free_total": list(torch.cuda.mem_get_info()),
        "packages": versions,
    }
    print(json.dumps(device), flush=True)
    jobs = json.loads(Path(args.jobs).read_text(encoding="utf-8"))
    if args.smoke:
        jobs = jobs[:1]
    torch.set_num_threads(4)
    settings = {
        "seed": 2026,
        "processing_resolution": args.resolution,
        "batch_size": 1,
        "ensemble_size": 3 if args.quality == "ensemble" else 1,
        "num_inference_steps": 10 if args.quality == "ensemble" else None,
        "output_uncertainty": args.quality == "ensemble",
        "match_input_resolution": True,
        "resample_method_input": "bilinear",
        "resample_method_output": "bilinear",
    }
    report = {"device": device, "runs": []}
    for role, (checkpoint, pipeline_class, pinned_revision) in MODELS.items():
        revision_file = output / f"{role}-revision.json"
        if revision_file.exists():
            revision = json.loads(revision_file.read_text())["revision"]
            if revision != pinned_revision:
                raise ValueError("Cached checkpoint revision differs from this recorded experiment")
        else:
            revision = HfApi().model_info(checkpoint, revision=pinned_revision).sha
            revision_file.write_text(json.dumps({"checkpoint": checkpoint, "revision": revision}))
        start = time.perf_counter()
        pipe = getattr(diffusers, pipeline_class).from_pretrained(
            checkpoint,
            revision=revision,
            variant="fp16",
            torch_dtype=torch.float16,
            cache_dir=str(output / "weights"),
        )
        # 8 GB GPU also drives the desktop. Keep just the active component on it.
        pipe.enable_model_cpu_offload()
        pipe.vae.enable_tiling()
        pipe.set_progress_bar_config(disable=True)
        load_seconds = time.perf_counter() - start
        properties = dict(getattr(pipe, "target_properties", {}))
        print(
            json.dumps(
                {
                    "role": role,
                    "revision": revision,
                    "properties": properties,
                    "defaults": dict(pipe.config),
                    "load_seconds": load_seconds,
                }
            ),
            flush=True,
        )
        for job in jobs:
            image = Image.open(job["photo"]).convert("RGB")
            source_hash = hashlib.sha256(np.asarray(image).tobytes()).hexdigest()
            crop = job["crop"]
            image = image.crop(tuple(crop))
            identity = {
                "preprocessing_version": 1,
                "execution": {
                    "offload": "model_cpu_offload",
                    "vae_tiling": True,
                    "dtype": "float16",
                },
                "photo_sha256": source_hash,
                "crop": crop,
                "checkpoint": checkpoint,
                "revision": revision,
                "settings": settings,
                "packages": versions,
            }
            key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            destination = output / args.quality / job["name"]
            destination.mkdir(parents=True, exist_ok=True)
            filename = destination / f"{role}-{key[:16]}.npz"
            if filename.exists() and not args.smoke:
                report["runs"].append(activate_cached(filename, role, identity))
                print(f"CACHE {filename}", flush=True)
                continue
            for repeat in range(2 if args.smoke else 1):
                torch.cuda.reset_peak_memory_stats()
                start = time.perf_counter()
                with torch.inference_mode():
                    result = pipe(
                        image,
                        generator=torch.Generator(device="cuda").manual_seed(2026),
                        **{k: v for k, v in settings.items() if k != "seed"},
                    )
                torch.cuda.synchronize()
                elapsed = time.perf_counter() - start
                prediction = np.asarray(result.prediction, dtype=np.float32)
                if not np.isfinite(prediction).all():
                    raise ValueError(f"{role}: non-finite prediction")
                if role == "normals" and not np.allclose(
                    np.linalg.norm(prediction, axis=-1), 1, atol=0.02
                ):
                    raise ValueError("Normals are not unit vectors")
                metadata = {
                    **identity,
                    "role": role,
                    "pipeline": pipeline_class,
                    "target_properties": properties,
                    "prediction_shape": list(prediction.shape),
                    "source_size": job["size"],
                    "crop_size": list(image.size),
                    "preprocessing": "unwarped crop; pipeline bilinear resize and VAE padding",
                    "normal_frame": "x right, y up, z toward viewer; image rows down",
                    "load_seconds": load_seconds,
                    "inference_seconds": elapsed,
                    "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
                    "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
                    "device": device,
                    "repeat": repeat,
                }
                processed, padding, original_resolution = pipe.image_processor.preprocess(
                    image,
                    processing_resolution=args.resolution,
                    resample_method_input="bilinear",
                    device=torch.device("cpu"),
                    dtype=torch.float32,
                )
                metadata["transforms"] = {
                    "crop_origin_xy": crop[:2],
                    "original_crop_hw": list(original_resolution),
                    "processed_padded_hw": list(processed.shape[-2:]),
                    "padding": list(padding),
                    "output_pixel_centres": "integer pixel centres aligned to the original crop",
                }
                metadata["pipeline_defaults"] = dict(pipe.config)
                metadata["offload"] = "model_cpu_offload"
                metadata["vae_tiling"] = True
                expected = (
                    3 if role == "lighting" else 1,
                    image.height,
                    image.width,
                    1 if role == "depth" else 3,
                )
                if prediction.shape != expected:
                    raise ValueError(f"Unexpected {role} output layout: {prediction.shape}")
                if role != "normals" and (prediction.min() < 0 or prediction.max() > 1):
                    raise ValueError(f"{role}: prediction outside [0,1]")
                if role == "lighting" and (
                    properties.get("target_names") != ["albedo", "shading", "residual"]
                    or any(
                        properties[k]["prediction_space"] != "linear"
                        for k in properties["target_names"]
                    )
                ):
                    raise ValueError("Unexpected intrinsic property ordering or colour space")
                arrays = {"prediction": prediction, "metadata": np.array(json.dumps(metadata))}
                if result.uncertainty is not None:
                    arrays["uncertainty"] = np.asarray(result.uncertainty, dtype=np.float32)
                    if not np.isfinite(arrays["uncertainty"]).all():
                        raise ValueError("Non-finite uncertainty")
                np.savez_compressed(filename, **arrays)
                (destination / f"{role}.json").write_text(
                    json.dumps({"file": filename.name, **metadata}, indent=2), encoding="utf-8"
                )
                report["runs"].append(metadata)
                print(
                    json.dumps(
                        {
                            "role": role,
                            "photo": job["name"],
                            "seconds": elapsed,
                            "shape": list(prediction.shape),
                            "peak_mb": metadata["peak_allocated_bytes"] / 2**20,
                            "repeat": repeat,
                        }
                    ),
                    flush=True,
                )
        del pipe
        gc.collect()
        torch.cuda.empty_cache()
        (
            output / ("smoke-report.json" if args.smoke else f"{args.quality}-report.json")
        ).write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
