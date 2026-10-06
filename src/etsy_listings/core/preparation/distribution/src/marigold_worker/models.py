"""Pinned models. Imported only inside the isolated inference process."""

from __future__ import annotations

import gc
import importlib.metadata
import platform
import time
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
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
PACKAGES = (
    "torch",
    "diffusers",
    "transformers",
    "accelerate",
    "huggingface-hub",
    "numpy",
    "pillow",
    "safetensors",
    "scipy",
)
MODEL_RAM_BUDGET = 4 * 1024**3


class Models:
    def __init__(self, weights: Path) -> None:
        import diffusers
        import torch

        # Native SciPy BLAS DLL loading stalled after the control reader started.
        # Resolve pipeline dependencies on the model thread before the handshake.
        self.pipeline_classes = {
            role: getattr(diffusers, pipeline_class)
            for role, (_, pipeline_class, _) in MODELS.items()
        }

        if platform.system() != "Windows" or not torch.cuda.is_available():
            raise RuntimeError(
                "Native Windows with CUDA is required. Install a compatible NVIDIA driver, "
                "then run etsy-listings marigold setup."
            )
        torch.set_num_threads(4)
        self.weights = weights
        self.pipe: Any = None
        self.role: str | None = None
        self.model_bytes = 0

    def capabilities(self) -> dict[str, Any]:
        import torch

        return {
            "engine_version": importlib.metadata.version("etsy-marigold-worker"),
            "roles": list(MODELS),
            "cuda": True,
            "gpu": torch.cuda.get_device_name(),
            "cuda_version": torch.version.cuda,
            "model_ram_budget": MODEL_RAM_BUDGET,
            "resident_models": 1,
            "installed_packages": {
                d.metadata["Name"].lower().replace("_", "-"): d.version
                for d in importlib.metadata.distributions()
                if d.metadata["Name"]
            },
            "packages": {p: importlib.metadata.version(p) for p in PACKAGES},
        }

    def infer(
        self, role: str, image: Image.Image, settings: dict[str, int]
    ) -> tuple[NDArray[np.float32], dict[str, Any]]:
        import psutil
        import torch

        checkpoint, pipeline_class, revision = MODELS[role]
        started = time.perf_counter()
        reused = self.role == role
        if not reused:
            # Bound retained pipelines to one. Components of only that pipeline
            # enter CUDA via accelerate's model_cpu_offload hooks (ADR-0053).
            self.pipe = None
            self.role = None
            gc.collect()
            torch.cuda.empty_cache()
            pipe = self.pipeline_classes[role].from_pretrained(
                str(self.weights / revision),
                variant="fp16",
                torch_dtype=torch.float16,
                local_files_only=True,
            )
            tensors = {}
            for component in pipe.components.values():
                if isinstance(component, torch.nn.Module):
                    for tensor in list(component.parameters()) + list(component.buffers()):
                        tensors[tensor.data_ptr()] = tensor.nelement() * tensor.element_size()
            self.model_bytes = sum(tensors.values())
            if self.model_bytes > MODEL_RAM_BUDGET:
                raise RuntimeError("Pinned pipeline exceeds the supported 4 GiB model RAM budget")
            pipe.enable_model_cpu_offload()
            pipe.vae.enable_tiling()
            pipe.set_progress_bar_config(disable=True)
            self.pipe, self.role = pipe, role
        load_seconds = time.perf_counter() - started
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        with torch.inference_mode():
            result = self.pipe(
                image,
                generator=torch.Generator(device="cuda").manual_seed(2026),
                processing_resolution=768,
                batch_size=1,
                output_uncertainty=False,
                match_input_resolution=True,
                resample_method_input="bilinear",
                resample_method_output="bilinear",
                **settings,
            )
        torch.cuda.synchronize()
        elapsed = time.perf_counter() - started
        prediction = np.asarray(result.prediction, dtype=np.float32)
        properties = dict(getattr(self.pipe, "target_properties", {}))
        if role == "lighting" and (
            properties.get("target_names") != ["albedo", "shading", "residual"]
            or any(
                properties[k]["prediction_space"] != "linear" for k in properties["target_names"]
            )
        ):
            raise ValueError("Unsupported intrinsic property ordering or colour space")
        processed, padding, original = self.pipe.image_processor.preprocess(
            image,
            processing_resolution=768,
            resample_method_input="bilinear",
            device=torch.device("cpu"),
            dtype=torch.float32,
        )
        metadata = dict(
            checkpoint=checkpoint,
            revision=revision,
            role=role,
            seed=2026,
            processing_resolution=768,
            settings=settings,
            target_properties=properties,
            normal_frame="x right, y up, z toward viewer; image rows down",
            transforms={
                "original_crop_hw": list(original),
                "processed_padded_hw": list(processed.shape[-2:]),
                "padding": list(padding),
                "output_pixel_centres": "integer pixel centres aligned to original crop",
            },
            load_seconds=load_seconds,
            inference_seconds=elapsed,
            warm_reuse=reused,
            resident_model_bytes=self.model_bytes,
            peak_allocated_bytes=torch.cuda.max_memory_allocated(),
            peak_reserved_bytes=torch.cuda.max_memory_reserved(),
            process_rss_bytes=psutil.Process().memory_info().rss,
            **self.capabilities(),
        )
        return prediction, metadata
