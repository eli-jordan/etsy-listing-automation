"""THROWAWAY Marigold garment reviewer. GPU inference is a separate offline step.

Run with --root, --samples, --output (the worker cache), optionally --design.
Never writes template YAML, listings, production render code or dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
import prototype_marigold_inputs as inputs
import prototype_marigold_math as math
import prototype_marigold_segmentation as segmentation
import prototype_surface as old
import prototype_surface_math as classical
import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field, field_validator

from etsy_listings.render import (
    Layer,
    Point,
    RenderConfig,
    encode_png,
    height_map,
    load_design,
    load_template_base,
    luminance_map,
    render_scene,
)
from etsy_listings.workspace import to_native_path

METHODS = {
    "selected": "Selected complete pipeline",
    "production": "Current production renderer",
    "production-photo": "Production mapping / shared photographic lighting",
    "classical": "Classical mapping / shared photographic lighting",
    "normals-photo": "Normals / photographic lighting",
    "normals-iid": "Normals / IID lighting",
    "depth-iid": "Normals + depth / IID lighting",
    "texture-off": "Normals / IID / texture off",
    "residual-on": "Normals / IID / restrained residual",
}
DIAGNOSTICS = [
    "normals",
    "shading",
    "albedo",
    "residual",
    "depth",
    "uncertainty",
    "visibility",
    "patches",
    "material",
    "strain",
    "discontinuities",
    "reconstruction",
]


def diagnostic(kind: str) -> math.Pixels:
    if kind in {"grid", "landscape"}:
        return old.diagnostic(kind)
    image = Image.new("RGBA", (768, 768))
    draw = ImageDraw.Draw(image)
    if kind == "white":
        draw.rectangle((32, 32, 736, 736), fill="white")
    elif kind == "colour":
        for x, colour in enumerate(["#ff2222", "#00de68", "#2255ff", "#ffe01b"]):
            draw.rectangle((32 + x * 176, 32, 207 + x * 176, 736), fill=colour)
    elif kind == "text":
        for y in range(48, 720, 28):
            draw.text(
                (50, y),
                "MASTER OF PACKETS 0123456789 / thin text / AaBbCc",
                fill="white",
                font_size=18,
            )
    elif kind == "edges":
        # Hidden saturated RGB is deliberately adversarial: zero alpha must isolate it.
        image = Image.new("RGBA", (768, 768), (255, 0, 255, 0))
        draw = ImageDraw.Draw(image)
        for radius in [280, 200, 120]:
            draw.ellipse(
                (384 - radius, 384 - radius, 384 + radius, 384 + radius), outline="white", width=2
            )
        draw.polygon([(64, 700), (384, 64), (704, 700)], outline="cyan", width=4)
    else:
        raise ValueError("Unknown diagnostic artwork")
    return np.asarray(image, np.uint8)


class Stroke(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    points: list[tuple[float, float]] = Field(min_length=1, max_length=5000)
    radius: float = Field(default=12, gt=0, le=300)
    polygon: bool = False
    restore: bool = False


class Patch(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    points: list[tuple[float, float]] = Field(min_length=3, max_length=100)
    offset: tuple[float, float] = (0.04, 0)
    order: int = Field(default=1, ge=0, le=100)

    @field_validator("offset")
    @classmethod
    def bounded_offset(cls, value: tuple[float, float]) -> tuple[float, float]:
        if max(abs(value[0]), abs(value[1])) > 0.5:
            raise ValueError("Hidden material offset must be within half the print span")
        return value


class Anchor(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    point: tuple[float, float]
    uv: tuple[float, float]


class Controls(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    box: list[tuple[float, float]] = Field(min_length=4, max_length=4)
    strokes: list[Stroke] = Field(default_factory=list, max_length=300)
    patches: list[Patch] = Field(default_factory=list, max_length=30)
    anchors: list[Anchor] = Field(default_factory=list, max_length=20)
    auto_mask: bool = True
    depth: bool = False
    illumination: Literal["iid", "photographic"] = "iid"
    texture: float = Field(default=0.25, ge=0, le=1)
    residual: float = Field(default=0, ge=0, le=1)


class Evidence:
    def __init__(self, directory: Path, photo_hash: str, size: tuple[int, int]) -> None:
        self.arrays = {}
        self.provenance = {}
        for role in ["normals", "lighting", "depth"]:
            pointer = json.loads((directory / f"{role}.json").read_text(encoding="utf-8"))
            file = directory / pointer["file"]
            if file.resolve().parent != directory.resolve():
                raise ValueError("Prediction pointer escapes its case directory")
            with np.load(file, allow_pickle=False) as archive:
                metadata = json.loads(str(archive["metadata"]))
                prediction = archive["prediction"].astype(np.float32)
                uncertainty = (
                    archive["uncertainty"].astype(np.float32) if "uncertainty" in archive else None
                )
            if metadata["photo_sha256"] != photo_hash or metadata["source_size"] != list(size):
                raise ValueError("Prediction belongs to a different photo")
            x0, y0, x1, y1 = metadata["crop"]
            shape = (3 if role == "lighting" else 1, y1 - y0, x1 - x0, 1 if role == "depth" else 3)
            if prediction.shape != shape or not np.isfinite(prediction).all():
                raise ValueError(f"Invalid {role} prediction shape or values")
            if not (0 <= x0 < x1 <= size[0] and 0 <= y0 < y1 <= size[1]):
                raise ValueError("Invalid inference crop")
            if role == "lighting":
                props = metadata["target_properties"]
                if props["target_names"] != ["albedo", "shading", "residual"] or any(
                    props[k]["prediction_space"] != "linear" for k in props["target_names"]
                ):
                    raise ValueError("Unexpected Lighting output ordering or colour space")
            if uncertainty is not None and (
                not np.isfinite(uncertainty).all() or uncertainty.min() < 0
            ):
                raise ValueError("Invalid uncertainty values")
            self.arrays[role] = (prediction, uncertainty)
            self.provenance[role] = metadata

    def field(
        self, role: str, xy: math.Float, component: int = 0, uncertainty: bool = False
    ) -> math.Float:
        prediction, spread = self.arrays[role]
        origin = np.asarray(self.provenance[role]["crop"][:2], np.float32)
        if uncertainty:
            if spread is None:
                return np.zeros(xy.shape[:2], np.float32)
            field = spread[component]
        else:
            field = prediction[component]
        result = math.sample(field, xy - origin, cv2.BORDER_CONSTANT)
        if result.ndim == 3 and result.shape[-1] == 1:
            result = result[..., 0]
        if uncertainty and result.ndim == 3:
            result = np.mean(result, axis=-1)
        return result

    def normals(self, xy: math.Float) -> tuple[math.Float, math.Float]:
        normals = self.field("normals", xy)
        length = np.linalg.norm(normals, axis=-1)
        normals /= np.maximum(length[..., None], 1e-8)
        spread = self.field("normals", xy, uncertainty=True)
        has_uncertainty = self.arrays["normals"][1] is not None
        confidence = 1 / (1 + spread * 30) if has_uncertainty else np.full(length.shape, 0.65)
        return normals, (confidence * (length > 0.5)).astype(np.float32)


class Trial:
    def __init__(
        self,
        samples: list[dict],
        output: Path,
        artwork: math.Pixels,
        quality: str,
        artwork_kind: str = "custom",
    ) -> None:
        self.samples = samples
        self.output = output
        self.quality = quality
        self.artwork = artwork
        self.custom_artwork = artwork.copy()
        self.artwork_kind = artwork_kind
        self.lock = threading.RLock()
        self.active = -1
        self.saved = {}
        self.select(0)

    def select(self, index: int) -> None:
        if self.active >= 0:
            self.saved[self.active] = (self.controls.model_copy(deep=True), self.imported)
        sample = self.samples[index]
        self.active = index
        self.base = load_template_base(Path(sample["path"]))
        h, w = self.base.shape[:2]
        self.photo_hash = hashlib.sha256(self.base.tobytes()).hexdigest()
        scale = min(1, 880 / max(h, w))
        self.preview_size = (round(w * scale), round(h * scale))
        self.controls, self.imported = self.saved.get(
            index, (Controls(box=sample["box"], strokes=sample.get("strokes", [])), None)
        )
        self.key = None
        self.calibrations = {}
        self.evidence = None
        self.outputs = {}
        self.diagnostics = {}

    def reset_calibration(self) -> None:
        """Restore source placement/corrections, retaining the chosen appearance."""
        sample = self.samples[self.active]
        self.controls = Controls(
            box=sample["box"],
            strokes=sample.get("strokes", []),
            depth=self.controls.depth,
            illumination=self.controls.illumination,
            texture=self.controls.texture,
            residual=self.controls.residual,
        )
        self.imported = None
        self.key = None

    def metadata(self) -> dict:
        return {
            "samples": [{"name": s["name"], "provenance": s["provenance"]} for s in self.samples],
            "active": self.active,
            "size": [self.base.shape[1], self.base.shape[0]],
            "controls": self.controls.model_dump(),
            "artwork_kind": self.artwork_kind,
            "imported": self.imported is not None,
            "methods": METHODS,
            "diagnostics": DIAGNOSTICS,
            "quality": self.quality,
            "inference": "offline cached fields; this server never imports torch",
        }

    def visibility(self, cloth: math.Float) -> math.Float:
        result = cloth.copy() if self.controls.auto_mask else np.ones(cloth.shape, np.float32)
        for stroke in self.controls.strokes:
            mask = np.zeros(result.shape, np.uint8)
            points = np.rint(stroke.points).astype(np.int32)
            if stroke.polygon:
                cv2.fillPoly(mask, [points], 1, lineType=cv2.LINE_8)
            else:
                radius = max(1, round(stroke.radius))
                cv2.polylines(mask, [points], False, 1, thickness=2 * radius, lineType=cv2.LINE_8)
                for point in (points[0], points[-1]):
                    cv2.circle(mask, tuple(point), radius, 1, thickness=-1, lineType=cv2.LINE_8)
            result[mask > 0] = 1 if stroke.restore else 0
        return result

    def prepare(self) -> dict:
        if self.imported is not None:
            self.calibrations = {"normals": self.imported, "depth": self.imported}
            return {
                **self.imported.metadata["diagnostics"],
                "imported": True,
                "offline": True,
                "fallbacks": ["Imported artifact: geometry comparators are unavailable"],
            }
        key = json.dumps(self.controls.model_dump(), sort_keys=True)
        if key == self.key:
            return self.metrics
        start = time.perf_counter()
        h, w = self.base.shape[:2]
        size = (w, h)
        box = np.asarray(self.controls.box, np.float32)
        if not cv2.isContourConvex(box) or cv2.contourArea(box) < 100:
            raise ValueError("Choose a convex, uncrossed quad in TL, TR, BR, BL order")
        directory = self.output / self.quality / self.samples[self.active]["name"]
        if self.evidence is None:
            self.evidence = Evidence(directory, self.photo_hash, size)
        crop = self.evidence.provenance["normals"]["crop"]
        if np.any(box.min(axis=0) < crop[:2]) or np.any(box.max(axis=0) >= crop[2:]):
            raise ValueError(
                "Placement leaves the cached inference crop; generate fields with more context"
            )
        yy, xx = np.mgrid[:h, :w].astype(np.float32)
        xy = np.stack([xx, yy], -1)
        mesh = 49
        grid = math.placement_grid(box, mesh)
        width = float((np.linalg.norm(box[1] - box[0]) + np.linalg.norm(box[2] - box[3])) / 2)
        normals, confidence = self.evidence.normals(grid)
        patches = [patch.model_dump() for patch in self.controls.patches]
        full_ids = math.patch_labels(size, patches)
        grid_ids = math.sample_labels(full_ids, grid)
        cloth, mask_metrics = segmentation.propose(self.base, box)
        visible = self.visibility(cloth)
        confidence *= math.sample(visible, grid)
        depth = self.evidence.field("depth", grid)
        depth_confidence = 1 / (1 + self.evidence.field("depth", grid, uncertainty=True) * 30)
        full_normals, full_confidence = self.evidence.normals(xy)
        full_confidence *= 1 / (1 + self.evidence.field("lighting", xy, 1, uncertainty=True) * 30)
        shading = self.evidence.field("lighting", xy, 1)
        albedo = self.evidence.field("lighting", xy, 0)
        residual = self.evidence.field("lighting", xy, 2)
        # Normalize only inside intended print and visible garment, not the scene.
        print_region = math.polygon_mask(size, self.controls.box)
        fields, light_metrics = math.lighting_fields(
            self.base, shading, albedo, residual, visible * print_region, full_confidence
        )
        anchors = []
        inverse = np.linalg.inv(
            cv2.getPerspectiveTransform(np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32), box)
        )
        for anchor in self.controls.anchors:
            location = cv2.perspectiveTransform(np.array([[anchor.point]], np.float32), inverse)[
                0, 0
            ]
            anchors.append({"location": location.tolist(), "uv": anchor.uv})
        geometry_metrics = {}
        for method in ["normals", "depth"]:
            surface, metrics = math.integrate(
                grid / width,
                normals,
                confidence,
                grid_ids,
                depth if method == "depth" else None,
                depth_confidence,
            )
            uv, flat_metrics = math.flatten(surface, grid_ids, anchors)
            material, valid, patch_ids = math.bake(uv, box, size, patches, grid_ids)
            valid *= visible
            patch_ids[valid == 0] = 0
            geometry_metrics[method] = {**metrics, **flat_metrics}
            self.calibrations[method] = math.Calibration(
                material,
                valid,
                patch_ids,
                fields[self.controls.illumination],
                fields["texture"],
                fields["residual"],
                {},
            )
            if method == "normals":
                self.uv = uv
                # Surface metric distortion, per-edge averaged onto visible nodes.
                a, b, degree = classical.graph(mesh)
                surface_p = surface.reshape(-1, 3)
                actual = np.linalg.norm(surface_p[b] - surface_p[a], axis=-1)
                canonical = uv.reshape(-1, 2) * [1, (np.linalg.norm(box[3] - box[0]) / width)]
                strain = np.abs(
                    np.linalg.norm(canonical[b] - canonical[a], axis=-1) / np.maximum(actual, 1e-8)
                    - 1
                )
                per_node = (
                    np.bincount(a, weights=strain, minlength=mesh * mesh)
                    + np.bincount(b, weights=strain, minlength=mesh * mesh)
                ) / degree
                self.strain = per_node.reshape(mesh, mesh).astype(np.float32)
        fallbacks = [
            "Hidden cloth offsets are priors; real self-overlap needs an explicit split",
            "Orthographic camera; perspective has not been fitted",
        ]
        for method, metrics in geometry_metrics.items():
            if metrics["grazing_fraction"] > 0.01:
                fallbacks.append(
                    f"{method}: grazing regions downweighted; using the placement prior there"
                )
            if metrics["orientation_barrier_steps"]:
                fallbacks.append(
                    f"{method}: orientation barrier restricted optimization; inspect the crease"
                )
            if "fallback" in metrics["depth"]:
                fallbacks.append(metrics["depth"]["fallback"])
        self.metrics = {
            "geometry": geometry_metrics,
            "lighting": light_metrics,
            "segmentation": mask_metrics,
            "fallbacks": fallbacks,
            "manual_patches": len(patches),
            "manual_anchors": len(anchors),
            "uncertainty_available": self.evidence.arrays["normals"][1] is not None,
            "fit_seconds": round(time.perf_counter() - start, 3),
            "imported": False,
        }
        provenance = {
            role: {k: v for k, v in meta.items() if k not in {"device"}}
            for role, meta in self.evidence.provenance.items()
        }
        for method, calibration in self.calibrations.items():
            calibration.metadata = {
                "format": "marigold-garment-v1",
                "photo_sha256": self.photo_hash,
                "size": [w, h],
                "controls": self.controls.model_dump(),
                "geometry": method,
                "render_settings": {
                    "texture": self.controls.texture,
                    "residual": self.controls.residual,
                },
                "camera": "orthographic: x right, y down, z toward viewer",
                "pixel_centres": "integer photo centres; half-pixel transform for preview resize",
                "illumination": light_metrics,
                "solver": {"mesh": mesh, "smoothness": 0.003, "version": 1},
                "provenance": provenance,
                "diagnostics": self.metrics,
                "patch_order": "larger order is frontmost",
            }
        small_xy = np.stack(
            np.mgrid[: self.preview_size[1], : self.preview_size[0]][::-1], -1
        ).astype(np.float32)
        small_xy = (small_xy + 0.5) * np.array(
            [w / self.preview_size[0], h / self.preview_size[1]]
        ) - 0.5
        n, _ = self.evidence.normals(small_xy)
        self.diagnostics = {
            "normals": np.rint((n + 1) * 127.5).clip(0, 255).astype(np.uint8),
            "shading": classical.display(classical.resize(shading, self.preview_size)),
            "albedo": classical.display(classical.resize(albedo, self.preview_size)),
            "residual": classical.display(classical.resize(residual, self.preview_size)),
            "depth": self.colour_scalar(self.evidence.field("depth", small_xy)),
            "uncertainty": self.colour_scalar(
                self.evidence.field("normals", small_xy, uncertainty=True) * 8
            ),
            "visibility": self.colour_scalar(classical.resize(visible, self.preview_size)),
            "patches": self.colour_scalar(
                classical.resize(full_ids.astype(np.float32), self.preview_size)
                / max(2, len(patches) + 1)
            ),
            "strain": self.colour_scalar(self.strain * 4),
            "material": np.clip(
                classical.resize(self.calibrations["normals"].material, self.preview_size) * 255,
                0,
                255,
            ).astype(np.uint8),
            "reconstruction": classical.display(
                classical.resize(albedo * shading + residual, self.preview_size)
            ),
        }
        material_vis = self.diagnostics["material"]
        self.diagnostics["material"] = np.concatenate(
            [material_vis, np.zeros((*material_vis.shape[:2], 1), np.uint8)], -1
        )
        # Suggest discontinuities for inspection only. No dark-line-as-overlap decision.
        gradient = np.linalg.norm(np.gradient(n, axis=0), axis=-1) + np.linalg.norm(
            np.gradient(n, axis=1), axis=-1
        )
        diagnostic_photo = classical.resize(self.base, self.preview_size).copy()
        candidates = gradient > max(0.13, float(np.percentile(gradient, 97)))
        diagnostic_photo[candidates] = [255, 95, 70]
        self.diagnostics["discontinuities"] = diagnostic_photo
        self.fields = fields
        self.key = key
        return self.metrics

    @staticmethod
    def colour_scalar(values: math.Float) -> math.Pixels:
        return cv2.applyColorMap(
            np.rint(np.clip(values, 0, 1) * 255).astype(np.uint8), cv2.COLORMAP_TURBO
        )[..., ::-1]

    def selected(self) -> math.Calibration:
        return (
            self.imported
            if self.imported is not None
            else self.calibrations["depth" if self.controls.depth else "normals"]
        )

    def image(self, name: str, full: bool = False) -> math.Pixels:
        if name in DIAGNOSTICS:
            return self.diagnostics.get(name, classical.resize(self.base, self.preview_size))
        calibration = self.selected()
        patch_ids = calibration.patch_ids
        if self.imported is not None and name != "selected":
            raise ValueError(
                "Reloaded calibration supports the selected result; refit to rebuild comparisons"
            )
        base = self.base if full else classical.resize(self.base, self.preview_size)
        size = (base.shape[1], base.shape[0])
        if name == "production":
            cfg = self.samples[self.active].get("config") or RenderConfig(
                bounding_box=tuple(Point(x=x, y=y) for x, y in self.controls.box)
            )
            sx, sy = size[0] / self.base.shape[1], size[1] / self.base.shape[0]
            cfg = cfg.model_copy(
                update={
                    "bounding_box": tuple(
                        Point(x=(x + 0.5) * sx - 0.5, y=(y + 0.5) * sy - 0.5)
                        for x, y in self.controls.box
                    )
                }
            )
            result = np.array(
                render_scene(
                    base,
                    [Layer(self.artwork, cfg)],
                    height=height_map(base),
                    luminance=luminance_map(base),
                )
            )
            visible = classical.resize(calibration.visibility, size)
            result[visible < 0.5] = base[visible < 0.5]
            return result
        if name == "selected":
            geometry, gain = calibration.material, calibration.gain
            texture = calibration.metadata["render_settings"]["texture"]
            residual = calibration.metadata["render_settings"]["residual"]
        else:
            geometry = self.calibrations["depth" if name == "depth-iid" else "normals"].material
            gain = self.fields[
                "photographic"
                if name in {"normals-photo", "classical", "production-photo"}
                else "iid"
            ]
            texture, residual = (
                (0 if name == "texture-off" else self.controls.texture),
                (0.3 if name == "residual-on" else 0),
            )
            if name in {"production-photo", "classical"}:
                patch_ids = np.ones(calibration.patch_ids.shape, np.int32)
                if name == "classical":
                    comparator = old.Trial([self.samples[self.active]], self.artwork)
                    comparator.controls = old.Controls(
                        box=self.controls.box,
                        strokes=[s.model_dump() for s in self.controls.strokes],
                    )
                    comparator.prepare()
                    geometry = classical.bake(
                        comparator.meshes["folds"],
                        np.asarray(self.controls.box, np.float32),
                        (self.base.shape[1], self.base.shape[0]),
                    )[0]
                else:
                    # Diagnostic inverse coordinates for the production passes'
                    # homography and gradient displacement, before its shading.
                    # Keep this comparator outside the production interface (A7).
                    cfg = self.samples[self.active].get("config")
                    h, w = self.base.shape[:2]
                    y, x = np.mgrid[:h, :w].astype(np.float32)
                    if cfg is not None and cfg.displace.enabled:
                        height = height_map(self.base)
                        x += (
                            cv2.Sobel(
                                height, cv2.CV_32F, 1, 0, ksize=3, borderType=cv2.BORDER_REPLICATE
                            )
                            * cfg.displace.strength
                            * 24
                        )
                        y += (
                            cv2.Sobel(
                                height, cv2.CV_32F, 0, 1, ksize=3, borderType=cv2.BORDER_REPLICATE
                            )
                            * cfg.displace.strength
                            * 24
                        )
                    inverse = cv2.getPerspectiveTransform(
                        np.asarray(self.controls.box, np.float32),
                        np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32),
                    )
                    geometry = cv2.perspectiveTransform(np.stack([x, y], -1), inverse)
        if not full:
            geometry, patch_ids = math.resize_material(geometry, patch_ids, size)
            gain = classical.resize(gain, size)
        return math.composite(
            base,
            self.artwork,
            geometry,
            classical.resize(calibration.visibility, size),
            gain,
            classical.resize(calibration.texture, size),
            classical.resize(calibration.residual, size),
            texture,
            residual,
            patch_ids,
        )

    def render(self) -> dict:
        metrics = self.prepare()
        self.outputs = {"selected": self.image("selected")}
        return metrics

    def artifact(self) -> bytes:
        self.prepare()
        return self.selected().dumps()

    def import_artifact(self, payload: bytes) -> None:
        calibration = math.Calibration.loads(
            payload, self.photo_hash, (self.base.shape[1], self.base.shape[0])
        )
        self.controls = Controls.model_validate(calibration.metadata["controls"])
        self.imported = calibration
        self.key = None


def create_app(trial: Trial) -> FastAPI:
    app = FastAPI(title="THROWAWAY Marigold garment trial")

    @app.get("/", response_class=HTMLResponse)
    def page() -> str:
        return Path(__file__).with_suffix(".html").read_text(encoding="utf-8")

    @app.get("/state")
    def state() -> dict:
        with trial.lock:
            return trial.metadata()

    @app.get("/photo")
    def photo() -> Response:
        with trial.lock:
            return Response(
                encode_png(Image.fromarray(classical.resize(trial.base, trial.preview_size))),
                media_type="image/png",
            )

    @app.post("/sample/{index}")
    def select(index: int) -> dict:
        with trial.lock:
            if not 0 <= index < len(trial.samples):
                raise HTTPException(404, "Unknown photo")
            trial.select(index)
            return trial.metadata()

    @app.post("/fit")
    def fit(controls: Controls) -> dict:
        with trial.lock:
            trial.controls = controls
            trial.imported = None
            try:
                return trial.render()
            except (ValueError, FileNotFoundError) as error:
                raise HTTPException(400, str(error)) from error

    @app.post("/reset")
    def reset() -> dict:
        with trial.lock:
            trial.reset_calibration()
            try:
                return {"state": trial.metadata(), "metrics": trial.render()}
            except (ValueError, FileNotFoundError) as error:
                raise HTTPException(400, str(error)) from error

    @app.get("/image/{name}")
    def image(name: str, full: bool = False) -> Response:
        with trial.lock:
            if name not in METHODS and name not in DIAGNOSTICS:
                raise HTTPException(404, "Unknown view")
            try:
                trial.prepare()
                result = trial.image(name, full)
            except ValueError as error:
                raise HTTPException(400, str(error)) from error
            return Response(encode_png(Image.fromarray(result)), media_type="image/png")

    @app.post("/artwork/{kind}")
    def artwork(kind: str) -> dict:
        with trial.lock:
            try:
                trial.artwork = (
                    trial.custom_artwork.copy() if kind == "custom" else diagnostic(kind)
                )
            except ValueError as error:
                raise HTTPException(400, str(error)) from error
            trial.artwork_kind = kind
            return trial.render()

    @app.post("/artwork")
    def upload_artwork(file: UploadFile) -> dict:
        with trial.lock:
            with Image.open(file.file) as source:
                if source.mode != "RGBA":
                    raise HTTPException(400, "Supply an RGBA PNG")
                trial.artwork = np.asarray(source, np.uint8).copy()
            trial.custom_artwork = trial.artwork.copy()
            trial.artwork_kind = "custom"
            return trial.render()

    @app.get("/calibration")
    def calibration() -> Response:
        with trial.lock:
            return Response(
                trial.artifact(),
                media_type="application/octet-stream",
                headers={"Content-Disposition": 'attachment; filename="marigold-garment-v1.npz"'},
            )

    @app.post("/calibration")
    def import_calibration(file: UploadFile) -> dict:
        with trial.lock:
            try:
                trial.import_artifact(file.file.read())
                return {"state": trial.metadata(), "metrics": trial.render()}
            except (ValueError, KeyError) as error:
                raise HTTPException(400, str(error)) from error

    @app.get("/metrics")
    def metrics() -> dict:
        with trial.lock:
            return trial.prepare()

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs.arguments(parser)
    parser.add_argument("--design")
    parser.add_argument("--port", type=int, default=8773)
    parser.add_argument("--start-sample", type=int, default=2)
    parser.add_argument("--quality", choices=["default", "ensemble"], default="ensemble")
    parser.add_argument(
        "--calibration", help="Start from an accepted map, including without inference caches"
    )
    args = parser.parse_args()
    artwork = load_design(to_native_path(args.design)) if args.design else diagnostic("landscape")
    trial = Trial(
        inputs.samples(args),
        to_native_path(args.output),
        artwork,
        args.quality,
        "custom" if args.design else "landscape",
    )
    trial.select(min(args.start_sample, len(trial.samples) - 1))
    if args.calibration:
        trial.import_artifact(to_native_path(args.calibration).read_bytes())
    else:
        trial.render()
    print(f"THROWAWAY Marigold viewer: http://localhost:{args.port}", flush=True)
    uvicorn.run(create_app(trial), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
