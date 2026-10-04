"""THROWAWAY experiment: surface fitting versus quad, with matched lighting.

Run: uv run python docs/research/marigold-20261001/prototype/prototype_surface.py --root <workspace> --template <name>
Standalone localhost evaluator; never modifies production templates or listings.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import threading
import time
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
import prototype_surface_math as math
import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field

from etsy_listings.core.render import (
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
from etsy_listings.core.workspace import Workspace, to_native_path


def diagnostic(kind: str) -> math.Pixels:
    image = Image.new("RGBA", (768, 768))
    draw = ImageDraw.Draw(image)
    if kind == "grid":
        for pos in range(48, 730, 48):
            draw.line([(pos, 48), (pos, 720)], fill="white", width=3)
            draw.line([(48, pos), (720, pos)], fill="white", width=3)
        for x, y in [(240, 240), (528, 240), (240, 528), (528, 528)]:
            draw.ellipse((x - 66, y - 66, x + 66, y + 66), outline="#ffb64b", width=7)
    else:
        # Deliberately crisp, authored vectors: distortions remain easy to see.
        draw.ellipse((190, 68, 578, 456), fill="#f2b557")
        draw.polygon([(65, 535), (258, 257), (422, 500), (567, 327), (711, 535)], fill="#efe7cd")
        draw.polygon([(258, 257), (202, 338), (254, 319), (282, 360), (305, 332)], fill="#314840")
        for y in range(552, 676, 27):
            draw.line([(125, y), (643, y)], fill="#90bfba", width=9)
        for x, y, scale in [(133, 500, 1), (599, 506, 1.15), (520, 574, 0.85)]:
            draw.polygon(
                [(x, y - 180 * scale), (x - 65 * scale, y), (x + 65 * scale, y)], fill="#263f38"
            )
            draw.line([(x, y), (x, y + 25)], fill="#efe7cd", width=8)
    return np.asarray(image, dtype=np.uint8)


class Controls(BaseModel):
    box: list[list[float]]
    curvature: float | None = Field(default=None, ge=0, le=0.4)
    relief: float = Field(default=0.045, ge=0, le=0.15)
    lighting: float = Field(default=0.7, ge=0, le=1)
    disabled: list[int] = Field(default_factory=list)
    strokes: list[dict] = Field(default_factory=list)
    mesh: Literal[17, 33, 49] = 49


class Trial:
    def __init__(
        self, samples: list[dict], artwork: math.Pixels, artwork_kind: str = "custom"
    ) -> None:
        self.samples = samples
        self.artwork = artwork
        self.packed_artwork = math.premultiply(artwork)
        self.artwork_kind = artwork_kind
        self.filtered_artwork = {}
        self.lock = threading.RLock()
        self.outputs: dict[str, math.Pixels] = {}
        self.active = 0
        self.imported = None
        self.select(0)

    def select(self, index: int) -> None:
        if hasattr(self, "controls"):
            self.samples[self.active]["edited_controls"] = self.controls.model_copy(deep=True)
        sample = self.samples[index]
        self.active = index
        self.base = load_template_base(Path(sample["path"]))
        self.photo_hash = hashlib.sha256(self.base.tobytes()).hexdigest()
        self.scale = min(1, 960 / max(self.base.shape[:2]))
        h, w = self.base.shape[:2]
        self.preview = math.resize(self.base, (round(w * self.scale), round(h * self.scale)))
        self.controls = sample.get(
            "edited_controls", Controls(box=sample["box"], strokes=sample.get("strokes", []))
        ).model_copy(deep=True)
        self.imported = None
        self.outputs.clear()
        self.prepared_key = None
        self.filtered_artwork.clear()

    def metadata(self) -> dict:
        return {
            "samples": [{"name": s["name"], "provenance": s["provenance"]} for s in self.samples],
            "active": self.active,
            "size": [self.base.shape[1], self.base.shape[0]],
            "controls": self.controls.model_dump(),
            "imported": self.imported is not None,
            "artwork_kind": self.artwork_kind,
        }

    def exclusion(self, size: tuple[int, int], scale: float) -> math.Pixels:
        image = np.zeros((size[1], size[0]), np.uint8)
        for stroke in self.controls.strokes:
            points = np.asarray(stroke["points"], np.float32) * scale
            if points.size == 0:
                continue
            points = np.round(points).astype(np.int32)
            if stroke.get("polygon"):
                cv2.fillPoly(image, [points], 255, lineType=cv2.LINE_8)
            else:
                width = max(1, round(float(stroke.get("radius", 12)) * scale))
                cv2.polylines(image, [points], False, 255, thickness=2 * width, lineType=cv2.LINE_8)
                for point in (points[0], points[-1]):
                    cv2.circle(image, tuple(point), width, 255, thickness=-1, lineType=cv2.LINE_8)
        return image

    def prepare(self) -> tuple[dict[str, math.Float], dict]:
        key = json.dumps(self.controls.model_dump(exclude={"lighting"}), sort_keys=True)
        if key == self.prepared_key:
            return self.meshes, self.prepared_metrics.copy()
        box = np.asarray(self.controls.box, np.float32) * self.scale
        if box.shape != (4, 2) or not np.isfinite(box).all():
            raise ValueError("Choose four finite corners in TL, TR, BR, BL order.")
        if not cv2.isContourConvex(box) or cv2.contourArea(box) < 100:
            raise ValueError("Print corners must form a convex, uncrossed quadrilateral.")
        size = (self.preview.shape[1], self.preview.shape[0])
        exclusion = self.exclusion(size, self.scale)
        analysis = math.analyse(self.preview, box, exclusion)
        aspect = (np.linalg.norm(box[3] - box[0]) + np.linalg.norm(box[2] - box[1])) / (
            np.linalg.norm(box[1] - box[0]) + np.linalg.norm(box[2] - box[3])
        )
        curve = analysis.curvature if self.controls.curvature is None else self.controls.curvature
        flat_surface, _ = math.fit_surface(analysis, aspect, 0, 0, [], self.controls.mesh)
        broad_surface, _ = math.fit_surface(analysis, aspect, curve, 0, [], self.controls.mesh)
        fold_surface, _ = math.fit_surface(
            analysis,
            aspect,
            curve,
            self.controls.relief,
            self.controls.disabled,
            self.controls.mesh,
        )
        neutral, _ = math.flatten(flat_surface)
        broad, broad_metrics = math.flatten(broad_surface)
        folds, fold_metrics = math.flatten(fold_surface)
        self.analysis = analysis
        self.meshes = {"quad": neutral, "surface": broad, "folds": folds}
        metrics = {
            "curvature": curve,
            "mesh": self.controls.mesh,
            "fold_candidates": analysis.folds,
            "active_folds": len(
                [f for f in analysis.folds if f["id"] not in self.controls.disabled]
            ),
            "surface": broad_metrics,
            "folds": fold_metrics,
        }
        self.prepared_key = key
        self.prepared_metrics = metrics
        return self.meshes, metrics.copy()

    def maps(self, name: str, full: bool) -> tuple:
        if self.imported is not None and name == "folds":
            material, valid, light = self.imported
            if full:
                return material, valid, light
            size = (self.preview.shape[1], self.preview.shape[0])
            return tuple(math.resize(field, size) for field in self.imported)
        base = self.base if full else self.preview
        scale = 1 if full else self.scale
        size = (base.shape[1], base.shape[0])
        box = np.asarray(self.controls.box, np.float32) * scale
        material, valid = math.bake(self.meshes[name], box, size)
        exclusion = self.exclusion(size, scale)
        visibility = 1 - math.blur(exclusion.astype(np.float32) / 255, max(0.5, scale))
        valid *= np.clip(visibility, 0, 1)
        light = math.project(self.analysis.light, box, size, 1)
        return material, valid, light

    def render(self) -> dict:
        start = time.perf_counter()
        _, metrics = self.prepare()
        box = tuple(Point(x=x * self.scale, y=y * self.scale) for x, y in self.controls.box)
        cfg = self.samples[self.active].get("config", RenderConfig(bounding_box=box))
        cfg = cfg.model_copy(update={"bounding_box": box})
        current = np.array(
            render_scene(
                self.preview,
                [Layer(self.artwork, cfg)],
                height=height_map(self.preview),
                luminance=luminance_map(self.preview),
            )
        )
        # Use the same visibility mask for the production comparator too.
        exclusion = self.exclusion((current.shape[1], current.shape[0]), self.scale)
        current[exclusion > 127] = self.preview[exclusion > 127]
        self.outputs = {"current": current}
        for name in self.meshes:
            self.outputs[name] = math.composite(
                self.preview,
                self.artwork_for(False),
                *self.maps(name, False),
                self.controls.lighting,
            )
        overlay = self.analysis.crop.copy()
        for fold in self.analysis.folds:
            label = int(fold["id"])
            pixels = self.analysis.labels == label
            color = [130, 130, 130] if label in self.controls.disabled else [255, 116, 58]
            overlay[pixels] = color
            cv2.putText(
                overlay,
                str(label),
                (round(fold["x"] * 255), round(fold["y"] * 255)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )
        self.outputs["diagnostic"] = overlay
        metrics["elapsed_ms"] = round((time.perf_counter() - start) * 1000)
        metrics["imported_map"] = self.imported is not None
        return metrics

    def artwork_for(self, full: bool) -> math.Float:
        # Footprint prefiltering prevents 4200px lettering from aliasing when
        # printed into a 500px region. Filter premultiplied linear pixels so
        # transparent RGB cannot bleed into the print edges.
        box = np.asarray(self.controls.box, np.float32) * (1 if full else self.scale)
        width = max(np.linalg.norm(box[1] - box[0]), np.linalg.norm(box[2] - box[3]))
        height = max(np.linalg.norm(box[3] - box[0]), np.linalg.norm(box[2] - box[1]))
        size = (
            min(self.artwork.shape[1], max(2, round(width * 1.5))),
            min(self.artwork.shape[0], max(2, round(height * 1.5))),
        )
        if size not in self.filtered_artwork:
            self.filtered_artwork[size] = cv2.resize(
                self.packed_artwork, size, interpolation=cv2.INTER_AREA
            )
        return self.filtered_artwork[size]

    def artifact(self) -> bytes:
        if not hasattr(self, "meshes"):
            self.render()
        buffer = io.BytesIO()
        material, valid, light = self.maps("folds", True)
        metadata = {
            "prototype": "classical-surface-v1",
            "photo_sha256": self.photo_hash,
            "size": [self.base.shape[1], self.base.shape[0]],
            "controls": self.controls.model_dump(),
        }
        np.savez_compressed(
            buffer,
            material=material,
            visibility=valid,
            lighting=light,
            metadata=np.array(json.dumps(metadata)),
        )
        return buffer.getvalue()

    def import_artifact(self, payload: bytes) -> None:
        with np.load(io.BytesIO(payload), allow_pickle=False) as archive:
            metadata = json.loads(str(archive["metadata"]))
            if metadata.get("prototype") != "classical-surface-v1":
                raise ValueError("Unsupported calibration format.")
            if metadata.get("photo_sha256") != self.photo_hash:
                raise ValueError("Calibration belongs to a different blank photo.")
            material, valid, light = (
                archive[key].astype(np.float32) for key in ("material", "visibility", "lighting")
            )
        h, w = self.base.shape[:2]
        if material.shape != (h, w, 2) or valid.shape != (h, w) or light.shape != (h, w):
            raise ValueError("Calibration dimensions do not match this photo.")
        if not all(np.isfinite(field).all() for field in (material, valid, light)):
            raise ValueError("Calibration contains non-finite values.")
        if valid.min() < 0 or valid.max() > 1 or light.min() < 0 or light.max() > 2:
            raise ValueError("Calibration contains invalid visibility or lighting.")
        self.controls = Controls.model_validate(metadata["controls"])
        self.imported = (material, valid, light)


def create_app(trial: Trial) -> FastAPI:
    app = FastAPI(title="THROWAWAY surface/fold trial")

    @app.get("/", response_class=HTMLResponse)
    def page() -> str:
        return Path(__file__).with_suffix(".html").read_text(encoding="utf-8")

    @app.get("/state")
    def state() -> dict:
        with trial.lock:
            return trial.metadata()

    @app.post("/sample/{index}")
    def select(index: int) -> dict:
        with trial.lock:
            if index < 0 or index >= len(trial.samples):
                raise HTTPException(404, "Unknown trial photo")
            trial.select(index)
            return trial.metadata()

    @app.get("/photo")
    def photo() -> Response:
        with trial.lock:
            return Response(encode_png(Image.fromarray(trial.preview)), media_type="image/png")

    @app.post("/fit")
    def fit(controls: Controls) -> dict:
        with trial.lock:
            trial.controls = controls
            trial.imported = None
            try:
                return trial.render()
            except ValueError as error:
                raise HTTPException(400, str(error)) from error

    @app.post("/artwork/{kind}")
    def choose_artwork(kind: str) -> dict:
        with trial.lock:
            if kind not in {"grid", "landscape"}:
                raise HTTPException(400, "Unknown diagnostic")
            trial.artwork = diagnostic(kind)
            trial.packed_artwork = math.premultiply(trial.artwork)
            trial.artwork_kind = kind
            trial.filtered_artwork.clear()
            return trial.render()

    @app.post("/artwork")
    def upload_artwork(file: UploadFile) -> dict:
        with trial.lock:
            image = Image.open(file.file)
            if image.mode != "RGBA":
                raise HTTPException(400, "Upload an RGBA PNG with transparency")
            trial.artwork = np.asarray(image, np.uint8)
            trial.packed_artwork = math.premultiply(trial.artwork)
            trial.artwork_kind = "custom"
            trial.filtered_artwork.clear()
            return trial.render()

    @app.get("/image/{name}")
    def image(name: str, full: bool = False) -> Response:
        with trial.lock:
            if name not in trial.outputs:
                raise HTTPException(404, "Render first")
            if full:
                if name not in trial.meshes:
                    raise HTTPException(400, "Full resolution is available for quad/surface/folds")
                output = math.composite(
                    trial.base,
                    trial.artwork_for(True),
                    *trial.maps(name, True),
                    trial.controls.lighting,
                )
            else:
                output = trial.outputs[name]
            return Response(encode_png(Image.fromarray(output)), media_type="image/png")

    @app.get("/calibration")
    def calibration() -> Response:
        with trial.lock:
            return Response(
                trial.artifact(),
                media_type="application/octet-stream",
                headers={"Content-Disposition": 'attachment; filename="surface.npz"'},
            )

    @app.post("/calibration")
    def upload_calibration(file: UploadFile) -> dict:
        with trial.lock:
            try:
                trial.import_artifact(file.file.read())
                return {"state": trial.metadata(), "metrics": trial.render()}
            except (ValueError, KeyError) as error:
                raise HTTPException(400, str(error)) from error

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="Workspace path; native or Cygwin path")
    parser.add_argument("--template")
    parser.add_argument("--colour", default="pepper", help="Photo colour slug")
    parser.add_argument("--photo", help="Alternative standalone blank photo")
    parser.add_argument("--samples", help="JSON list of additional photo paths/normalized boxes")
    parser.add_argument("--design", help="RGBA design; otherwise the built-in landscape")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--start-sample", type=int)
    parser.add_argument(
        "--controls", help="Saved controls or /state snapshot for the starting photo"
    )
    args = parser.parse_args()
    samples = []
    if args.template:
        workspace = Workspace.discover(
            root_override=to_native_path(args.root) if args.root else None
        )
        template = workspace.load_template_config(args.template)
        if template.kind == "multiple":
            cfg = template.render_config_for(template.placements[0])
        else:
            cfg = template.render_config()
        photo = workspace.scene_photo(
            args.template, args.colour if template.kind == "colour-matrix" else None
        ).path
        samples.append(
            {
                "name": f"{args.template} / {args.colour}",
                "path": str(photo),
                "provenance": "Genuine blank photograph",
                "config": cfg,
                "box": [[p.x, p.y] for p in cfg.bounding_box],
            }
        )
    if args.photo:
        photo = to_native_path(args.photo)
        w, h = Image.open(photo).size
        samples.append(
            {
                "name": photo.stem,
                "path": str(photo),
                "provenance": "Standalone photo; verify source",
                "box": [
                    [w * 0.3, h * 0.3],
                    [w * 0.7, h * 0.3],
                    [w * 0.7, h * 0.75],
                    [w * 0.3, h * 0.75],
                ],
            }
        )
    if args.samples:
        manifest = to_native_path(args.samples)
        for sample in json.loads(manifest.read_text(encoding="utf-8")):
            photo = to_native_path(sample["path"])
            w, h = Image.open(photo).size
            sample["path"] = str(photo)
            sample["box"] = [[x * w, y * h] for x, y in sample["box"]]
            for stroke in sample.get("strokes", []):
                stroke["points"] = [[x * w, y * h] for x, y in stroke["points"]]
            samples.append(sample)
    if not samples:
        parser.error("Supply --template and --root, or --photo")
    artwork = load_design(to_native_path(args.design)) if args.design else diagnostic("landscape")
    trial = Trial(samples, artwork, "custom" if args.design else "landscape")
    saved = {}
    if args.controls:
        saved = json.loads(to_native_path(args.controls).read_text(encoding="utf-8"))
    selected = args.start_sample if args.start_sample is not None else saved.get("active", 0)
    if not 0 <= selected < len(samples):
        parser.error("Starting photo index is outside the trial sample list")
    trial.select(selected)
    if args.controls:
        trial.controls = Controls.model_validate(saved.get("controls", saved))
    uvicorn.run(create_app(trial), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
