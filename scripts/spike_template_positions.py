"""Marigold padded-fit spike for per-listing template positions (option A).

Answers the spec's *Spike gate*
(docs/features/template-positions-20261102/spec.md): fit a Marigold template's
maps once over a padded quad that covers every pose the default limits allow,
apply a listing position as a UV affine at composite time, and compare that
with a direct fit of the adjusted box. Plan decision P1 makes this PR 1;
decision P2 restricts it to a throwaway workspace holding copies of real
templates.

Run with::

    uv run python scripts/spike_template_positions.py --workspace <throwaway> --out <dir>

The workspace holds ``mockup-templates/<name>/`` copies of prepared Marigold
templates. Their preparation evidence lives in the source workspace's
``.cache`` and is not copied (P2), and it would not cover the padded quad in
any case, so the harness runs Marigold inference once per template on a crop
planned for the padded quad. The predictions are kept under
``<workspace>/.cache/spike-evidence/<template>/``; reruns reuse them, so
everything after inference is deterministic. Results go to
``<out>/results.json`` and side-by-side PNGs to ``<out>``.

Research only: nothing here is production code, and nothing under ``src/``
changes. Helpers live in this script on purpose.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

import cv2
import numpy as np
import yaml
from numpy.typing import NDArray
from PIL import Image

from etsy_listings.core.application.preparation.evidence_reader import required_identity
from etsy_listings.core.preparation.artifacts import Manifest, MapPointer, read_maps
from etsy_listings.core.preparation.distribution.src.marigold_worker.protocol import Role
from etsy_listings.core.preparation.numerics import (
    Evidence,
    EvidenceIdentity,
    Placement,
    evidence_covers,
    plan_crop,
    prepare,
)
from etsy_listings.core.preparation.predictions import read_prediction
from etsy_listings.core.preparation.runtime import Runtime
from etsy_listings.core.preparation.worker_client import InferenceCall
from etsy_listings.core.render.config import MarigoldAppearance
from etsy_listings.core.render.material import (
    MaterialLayer,
    MaterialMaps,
    prepare_material_artwork,
    render_marigold_scene,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = (
    "cc1717-hanging-on-fence",
    "cc1717-man-with-tattoos-standing",
    "cc1717-woman-with-oversize-fit",
)
ROLES: tuple[Role, ...] = ("normals", "lighting", "depth")
CHART_SIZE = 1800
CHART_CELLS = 12
REAL_DESIGN = REPO_ROOT / "tests" / "fixtures" / "workspace" / "designs" / "take-a-hike.png"
VISIBLE = 0.95  # visibility above which a pixel counts as confident cloth
GARMENT = 0.5  # mask value above which a photo pixel is garment
EDGE_RING = 3  # pixels of the print boundary excluded from the interior metric
NOTICEABLE = 5.0  # ΔE76 above which a difference is plainly visible
HEAT_RANGE = 10.0
TONE_SIGMA = 6.0  # photo pixels  # ΔE76 mapped to the top of the heat map
PANEL_HEIGHT = 640
COMPOSITE_REPEATS = 3
LUMINANCE = np.array([0.2126, 0.7152, 0.0722], np.float32)
PERCENTILE = 70  # production lighting normalisation percentile


# ----------------------------------------------------------------------------
# Limits, poses and the box frame (spec: Scope and decisions, Allowed shape).


@dataclass(frozen=True)
class Limits:
    scale_min: float
    scale_max: float
    offset: float  # fraction of box width and height, each axis
    rotation: float  # degrees either way


DEFAULT_LIMITS = Limits(0.80, 1.10, 0.10, 15.0)
NARROWER_LIMITS = Limits(0.90, 1.05, 0.05, 10.0)  # the "limits change" refit
WIDER_LIMITS = Limits(0.70, 1.25, 0.15, 25.0)  # coverage check only


@dataclass(frozen=True)
class Pose:
    name: str
    scale: float = 1.0
    dx: float = 0.0  # fraction of box width
    dy: float = 0.0  # fraction of box height
    tilt: float = 0.0  # degrees; positive is clockwise on screen (y down)


def extreme_poses(limits: Limits) -> tuple[Pose, ...]:
    """Each limit alone, then the four combined corners: largest scale,
    largest offset diagonally, and the tilt that swings the leading corner
    furthest outward."""
    lo, hi, off, rot = limits.scale_min, limits.scale_max, limits.offset, limits.rotation
    return (
        Pose("identity"),
        Pose("scale-min", scale=lo),
        Pose("scale-max", scale=hi),
        Pose("offset-left", dx=-off),
        Pose("offset-right", dx=off),
        Pose("offset-up", dy=-off),
        Pose("offset-down", dy=off),
        Pose("tilt-ccw", tilt=-rot),
        Pose("tilt-cw", tilt=rot),
        Pose("corner-down-right", scale=hi, dx=off, dy=off, tilt=rot),
        Pose("corner-up-left", scale=hi, dx=-off, dy=-off, tilt=rot),
        Pose("corner-up-right", scale=hi, dx=off, dy=-off, tilt=-rot),
        Pose("corner-down-left", scale=hi, dx=-off, dy=off, tilt=-rot),
    )


@dataclass(frozen=True)
class BoxFrame:
    """The template box's own pre-homography frame: a ``width`` by ``height``
    rectangle (mean side lengths in photo pixels) mapped onto the box."""

    box: NDArray[np.float32]
    width: float
    height: float
    to_photo: NDArray[np.float64]

    @classmethod
    def of(cls, box: NDArray[np.float32]) -> BoxFrame:
        width = float(np.linalg.norm(box[1] - box[0]) + np.linalg.norm(box[2] - box[3])) / 2
        height = float(np.linalg.norm(box[3] - box[0]) + np.linalg.norm(box[2] - box[1])) / 2
        rectangle = np.array([[0, 0], [width, 0], [width, height], [0, height]], np.float32)
        to_photo = cv2.getPerspectiveTransform(rectangle, box).astype(np.float64)
        return cls(box, width, height, to_photo)

    def photo(self, points: NDArray[np.float64]) -> NDArray[np.float32]:
        mapped = cv2.perspectiveTransform(points.reshape(-1, 1, 2), self.to_photo)
        return cast(NDArray[np.float32], mapped.reshape(-1, 2).astype(np.float32))

    def pose_to_unit(self, pose: Pose) -> NDArray[np.float64]:
        """The 2x3 affine taking frame coordinates to the posed box's unit UV."""
        size = np.array([self.width, self.height])
        centre = size / 2
        shift = centre + np.array([pose.dx * self.width, pose.dy * self.height])
        angle = math.radians(pose.tilt)
        inverse = np.array(
            [[math.cos(angle), math.sin(angle)], [-math.sin(angle), math.cos(angle)]]
        )
        linear = inverse / pose.scale
        # The posed UV is the centre plus the inverse similarity of the frame
        # point's offset from the shifted centre, divided by the frame size.
        matrix = linear / size[:, None]
        return np.hstack([matrix, ((centre - linear @ shift) / size)[:, None]])

    def posed_box(self, pose: Pose) -> NDArray[np.float32]:
        size = np.array([self.width, self.height])
        centre = size / 2
        angle = math.radians(pose.tilt)
        rotation = np.array(
            [[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]]
        )
        unit = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float64) * size
        shift = centre + np.array([pose.dx * self.width, pose.dy * self.height])
        corners = shift + pose.scale * (unit - centre) @ rotation.T
        return self.photo(corners)

    def padded_rectangle(self, limits: Limits) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Origin and size, in frame coordinates, of the rectangle covering
        every pose the limits allow (the padded quad before the homography)."""
        angle = math.radians(limits.rotation)
        half_x = limits.scale_max * (
            self.width / 2 * math.cos(angle) + self.height / 2 * math.sin(angle)
        )
        half_y = limits.scale_max * (
            self.width / 2 * math.sin(angle) + self.height / 2 * math.cos(angle)
        )
        half = np.array([half_x + limits.offset * self.width, half_y + limits.offset * self.height])
        centre = np.array([self.width, self.height]) / 2
        return centre - half, 2 * half

    def padded_quad(self, limits: Limits) -> NDArray[np.float32]:
        origin, size = self.padded_rectangle(limits)
        unit = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float64)
        return self.photo(origin + unit * size)


# ----------------------------------------------------------------------------
# Option A: a listing position as a UV affine on padded maps (spec: Rendering,
# Marigold option A).


def uv_affine(frame: BoxFrame, limits: Limits, pose: Pose) -> NDArray[np.float64]:
    """Padded-map UV -> posed-box UV, as one 2x3 affine."""
    origin, size = frame.padded_rectangle(limits)
    padded_to_frame = np.array([[size[0], 0, origin[0]], [0, size[1], origin[1]], [0, 0, 1]])
    return cast(NDArray[np.float64], frame.pose_to_unit(pose) @ padded_to_frame)


def apply_position(
    maps: MaterialMaps, affine: NDArray[np.float64], *, renormalise: bool
) -> MaterialMaps:
    """The padded maps with UV transformed and visibility recomputed from the
    transformed UV. ``renormalise`` also rescales both lighting gains so their
    70th percentile over the posed print is 1, as a direct fit's would be."""
    material = (maps.material @ affine[:, :2].T + affine[:, 2]).astype(np.float32)
    inside = np.all((material >= 0) & (material <= 1), axis=-1)
    visibility = (maps.visibility * inside).astype(np.float32)
    estimated, photographic = maps.estimated, maps.photographic
    if renormalise:
        selected = visibility > VISIBLE
        if selected.any():
            estimated = _renormalised(estimated, selected)
            photographic = _renormalised(photographic, selected)
    return replace(
        maps,
        material=material,
        visibility=visibility,
        estimated=estimated,
        photographic=photographic,
        patch_ids=(visibility > 0).astype(np.int32),
    ).cropped_to_visibility()


def _renormalised(gain: NDArray[np.float32], selected: NDArray[np.bool_]) -> NDArray[np.float32]:
    exposure = float(np.percentile((gain @ LUMINANCE)[selected], PERCENTILE))
    return cast(NDArray[np.float32], np.clip(gain / max(exposure, 1e-3), 0.04, 1.7))


# ----------------------------------------------------------------------------
# Template data, evidence and inference.


@dataclass(frozen=True)
class Template:
    name: str
    box: NDArray[np.float32]
    appearance: MarigoldAppearance
    manifest: Manifest
    generation: Path
    base: NDArray[np.uint8]
    mask: NDArray[np.float32]


def load_template(workspace: Path, name: str) -> Template:
    folder = workspace / "mockup-templates" / name
    config = yaml.safe_load((folder / "template.yaml").read_text(encoding="utf-8"))
    box = np.array([[p["x"], p["y"]] for p in config["bounding_box"]], np.float32)
    maps = folder / "_renderer" / "maps"
    pointer = MapPointer.model_validate_json((maps / "current.json").read_bytes())
    generation = maps / "generations" / pointer.generation_id
    manifest = Manifest.model_validate_json((generation / "manifest.json").read_bytes())
    with Image.open(folder / manifest.preparation_inputs.photo.file) as photo:
        base = np.array(photo.convert("RGB"), np.uint8)
    with Image.open(folder / "_renderer" / "masks" / "edited.png") as image:
        mask = np.array(image.convert("L"), np.float32) / np.float32(255)
    appearance = MarigoldAppearance(**config["renderer"]["config"].get("appearance", {}))
    return Template(name, box, appearance, manifest, generation, base, mask)


def published_maps(template: Template) -> MaterialMaps:
    size = (template.base.shape[1], template.base.shape[0])
    return read_maps(template.generation / "placement.npz", template.manifest.placements[0], size)


def evidence_for(
    template: Template, quad: NDArray[np.float32], root: Path, timings: dict[str, Any]
) -> Evidence:
    """Predictions for the crop production would plan for ``quad``, inferred
    once and kept under ``root`` (relative paths are the worker's protocol)."""
    inputs = template.manifest.preparation_inputs
    size = (template.base.shape[1], template.base.shape[0])
    crop = plan_crop(quad, size)
    folder = root / template.name
    folder.mkdir(parents=True, exist_ok=True)
    record_path = folder / "evidence.json"
    record = json.loads(record_path.read_text()) if record_path.exists() else {}
    if record.get("rectangle") != list(crop.rectangle):
        record = {"rectangle": list(crop.rectangle), "checksums": {}, "seconds": {}}
        left, top, right, bottom = crop.rectangle
        Image.fromarray(template.base[top:bottom, left:right]).save(folder / "crop.png")
        settings = inputs.inference
        runtime = Runtime()
        with runtime.worker(runtime.inspect(), cache_root=root) as worker:
            for role in ROLES:
                started = time.perf_counter()
                result = worker.infer(
                    InferenceCall(
                        request_id=f"spike-{template.name}-{role}",
                        role=role,
                        input=f"{template.name}/crop.png",
                        output=f"{template.name}/{role}.npz",
                        size=crop.prediction_size,
                        num_inference_steps=settings.num_inference_steps,
                        ensemble_size=settings.ensemble_size,
                    )
                )
                record["seconds"][role] = time.perf_counter() - started
                record["checksums"][role] = result.checksum
        record_path.write_text(json.dumps(record, indent=2))
    timings["inference_seconds"] = record["seconds"]
    arrays = {
        role: read_prediction(
            folder / f"{role}.npz",
            role=role,
            checksum=record["checksums"][role],
            size=crop.prediction_size,
        )
        for role in ROLES
    }
    lighting = arrays["lighting"]
    return Evidence(
        crop=crop,
        identity=required_identity(inputs),
        normals=arrays["normals"][0],
        shading=lighting[1],
        albedo=lighting[0],
        residual=lighting[2],
        depth=arrays["depth"][0, :, :, 0],
    )


def covers(evidence: Evidence, quad: NDArray[np.float32], size: tuple[int, int]) -> bool:
    identity: EvidenceIdentity = evidence.identity
    return evidence_covers(evidence.crop, identity, quad, size, identity)


# ----------------------------------------------------------------------------
# Composites, metrics and pictures.


def chart_design() -> NDArray[np.uint8]:
    """A deterministic opaque test chart: hue cells, a black grid and text,
    so geometric and tonal differences show everywhere in the print."""
    cell = CHART_SIZE // CHART_CELLS
    rows, cols = np.mgrid[:CHART_CELLS, :CHART_CELLS]
    hue = ((rows * CHART_CELLS + cols) * 7 % 180).astype(np.uint8)
    value = np.where((rows + cols) % 2 == 0, 230, 150).astype(np.uint8)
    hsv = np.stack([hue, np.full_like(hue, 170), value], -1)
    cells = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    chart = np.ascontiguousarray(np.kron(cells, np.ones((cell, cell, 1), np.uint8)))
    for index in range(CHART_CELLS + 1):
        position = min(index * cell, CHART_SIZE - 3)
        chart[position : position + 3, :] = 0
        chart[:, position : position + 3] = 0
    for row in range(CHART_CELLS):
        cv2.putText(
            chart,
            f"R{row:02d} SPIKE",
            (cell // 6, row * cell + cell // 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.1,
            (20, 20, 20),
            3,
            cv2.LINE_AA,
        )
    alpha = np.full((CHART_SIZE, CHART_SIZE, 1), 255, np.uint8)
    return np.concatenate([chart, alpha], axis=-1)


def real_design() -> NDArray[np.uint8]:
    with Image.open(REAL_DESIGN) as image:
        return np.array(image.convert("RGBA"), np.uint8)


@dataclass(frozen=True)
class Design:
    name: str
    pixels: NDArray[np.uint8]
    premultiplied: NDArray[np.float32]


def compose(
    template: Template, design: Design, maps: MaterialMaps, timing: list[float]
) -> NDArray[np.uint8]:
    layer = MaterialLayer(design.pixels, maps, premultiplied=design.premultiplied)
    started = time.perf_counter()
    image = render_marigold_scene(template.base, [layer], appearance=template.appearance)
    timing.append(time.perf_counter() - started)
    return np.asarray(image, np.uint8)


def lab(rgb: NDArray[np.uint8]) -> NDArray[np.float32]:
    return cast(NDArray[np.float32], cv2.cvtColor(rgb.astype(np.float32) / 255, cv2.COLOR_RGB2Lab))


def difference(
    base: NDArray[np.uint8], reference: NDArray[np.uint8], candidate: NDArray[np.uint8]
) -> tuple[dict[str, float], NDArray[np.float32], NDArray[np.bool_]]:
    """CIE76 ΔE inside the print mask: every pixel either composite changed
    from the blank photo. Interior excludes a ring at the print boundary."""
    delta = np.linalg.norm(lab(reference) - lab(candidate), axis=-1)
    printed = (reference != base).any(-1) | (candidate != base).any(-1)
    kernel = np.ones((2 * EDGE_RING + 1, 2 * EDGE_RING + 1), np.uint8)
    interior = cv2.erode(printed.astype(np.uint8), kernel).astype(bool)
    values = delta[printed]
    inner = delta[interior] if interior.any() else values
    # Tone: ΔE after a blur wide enough to hide pixel-scale misregistration of
    # thin lines and text, leaving lighting and colour differences.
    tone = np.linalg.norm(
        lab(_blurred(reference, printed, base)) - lab(_blurred(candidate, printed, base)), axis=-1
    )
    return (
        {
            "mean": float(values.mean()),
            "p99": float(np.percentile(values, 99)),
            "interior_mean": float(inner.mean()),
            "interior_p99": float(np.percentile(inner, 99)),
            "over_5_percent": float((values > NOTICEABLE).mean() * 100),
            "tone_mean": float(tone[printed].mean()),
            "tone_p99": float(np.percentile(tone[printed], 99)),
        },
        delta.astype(np.float32),
        printed,
    )


def _blurred(
    image: NDArray[np.uint8], printed: NDArray[np.bool_], base: NDArray[np.uint8]
) -> NDArray[np.uint8]:
    """Blur only the print: outside it both composites keep the blank photo,
    so the blur never mixes in a difference from beyond the mask."""
    blurred = cv2.GaussianBlur(image, (0, 0), TONE_SIGMA)
    return np.where(printed[..., None], blurred, base).astype(np.uint8)


def displacement(
    reference: MaterialMaps, candidate: MaterialMaps, size: tuple[float, float]
) -> dict[str, float]:
    """Artwork misregistration in photo pixels: the UV difference over pixels
    both maps show, scaled by the posed box's side lengths ``size``."""
    width, height = reference.size

    def full(maps: MaterialMaps) -> tuple[NDArray[np.float32], NDArray[np.bool_]]:
        material = np.zeros((height, width, 2), np.float32)
        visible = np.zeros((height, width), bool)
        left, top, right, bottom = maps.extent
        material[top:bottom, left:right] = maps.material
        visible[top:bottom, left:right] = maps.visibility > 0
        return material, visible

    first, first_visible = full(reference)
    second, second_visible = full(candidate)
    both = first_visible & second_visible
    pixels = np.linalg.norm((first - second)[both] * np.array(size, np.float32), axis=-1)
    return {
        "mean_px": float(pixels.mean()),
        "p99_px": float(np.percentile(pixels, 99)),
        "max_px": float(pixels.max()),
        "visible_overlap": float(both.sum())
        / max(1.0, float((first_visible | second_visible).sum())),
    }


def garment_cover(mask: NDArray[np.float32], quad: NDArray[np.float32]) -> float:
    """Fraction of the quad's photo area that is garment in the edited mask."""
    inside = np.zeros(mask.shape, np.uint8)
    cv2.fillPoly(inside, [np.rint(quad).astype(np.int32)], (1,))
    area = inside.astype(bool)
    return float((mask[area] > GARMENT).mean()) if area.any() else 0.0


def side_by_side(
    path: Path,
    region: tuple[int, int, int, int],
    panels: tuple[NDArray[np.uint8], NDArray[np.uint8], NDArray[np.float32]],
    labels: tuple[str, str, str],
) -> None:
    left, top, right, bottom = region
    reference, candidate, delta = panels
    heat = cv2.applyColorMap(
        np.clip(delta / HEAT_RANGE * 255, 0, 255).astype(np.uint8), cv2.COLORMAP_INFERNO
    )[..., ::-1]
    images = [
        image[top:bottom, left:right]
        for image in (reference, candidate, np.ascontiguousarray(heat))
    ]
    scale = PANEL_HEIGHT / images[0].shape[0]
    size = (round(images[0].shape[1] * scale), PANEL_HEIGHT)
    tiles = []
    for image, label in zip(images, labels, strict=True):
        tile = np.ascontiguousarray(cv2.resize(image, size, interpolation=cv2.INTER_AREA))
        cv2.rectangle(tile, (0, 0), (size[0], 34), (255, 255, 255), -1)
        cv2.putText(tile, label, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2, cv2.LINE_AA)
        tiles.append(tile)
    Image.fromarray(np.hstack(tiles)).save(path, compress_level=6)


def crop_region(quad: NDArray[np.float32], shape: tuple[int, ...]) -> tuple[int, int, int, int]:
    margin = 40
    lo = np.maximum(np.floor(quad.min(axis=0)).astype(int) - margin, 0)
    hi = np.minimum(np.ceil(quad.max(axis=0)).astype(int) + margin, [shape[1], shape[0]])
    return int(lo[0]), int(lo[1]), int(hi[0]), int(hi[1])


# ----------------------------------------------------------------------------
# The run.


@contextmanager
def timed(into: dict[str, float], key: str) -> Iterator[None]:
    started = time.perf_counter()
    yield
    into[key] = time.perf_counter() - started


@dataclass(frozen=True)
class Context:
    template: Template
    frame: BoxFrame
    evidence: Evidence
    padded: MaterialMaps
    designs: tuple[Design, ...]
    out: Path


def run_template(template: Template, designs: tuple[Design, ...], args: Args) -> dict[str, Any]:
    print(f"== {template.name}", flush=True)
    frame = BoxFrame.of(template.box)
    size = (template.base.shape[1], template.base.shape[0])
    quad = frame.padded_quad(DEFAULT_LIMITS)
    timings: dict[str, Any] = {}
    evidence = evidence_for(template, quad, args.workspace / ".cache" / "spike-evidence", timings)
    original_crop = plan_crop(template.box, size).rectangle
    with timed(timings, "padded_fit"):
        padded = prepare(template.base, Placement(quad, template.mask), evidence).maps
    narrower = frame.padded_quad(NARROWER_LIMITS)
    with timed(timings, "refit_after_limits_change"):
        prepare(template.base, Placement(narrower, template.mask), evidence)
    context = Context(template, frame, evidence, padded, designs, args.out)
    poses = [run_pose(context, pose) for pose in extreme_poses(DEFAULT_LIMITS)]
    identity = run_identity_against_published(context)
    return {
        "template": template.name,
        "photo_size": list(size),
        "box": template.box.tolist(),
        "padded_quad": quad.tolist(),
        "evidence_crop": list(evidence.crop.rectangle),
        "original_evidence_crop": list(original_crop),
        "original_evidence_covers_padded_quad": _rect_covers(
            original_crop, plan_crop(quad, size).rectangle
        ),
        "padded_evidence_covers_wider_limits": covers(
            evidence, frame.padded_quad(WIDER_LIMITS), size
        ),
        "garment_cover": {
            "template_box": garment_cover(template.mask, template.box),
            "padded_quad": garment_cover(template.mask, quad),
        },
        "timings": timings,
        "poses": poses,
        "identity_vs_published": identity,
    }


def _rect_covers(outer: tuple[int, ...], inner: tuple[int, ...]) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and outer[2] >= inner[2]
        and outer[3] >= inner[3]
    )


def run_pose(context: Context, pose: Pose) -> dict[str, Any]:
    template, frame = context.template, context.frame
    box = frame.posed_box(pose)
    timings: dict[str, float] = {}
    with timed(timings, "direct_fit"):
        direct = prepare(template.base, Placement(box, template.mask), context.evidence).maps
    affine = uv_affine(frame, DEFAULT_LIMITS, pose)
    with timed(timings, "uv_affine"):
        option_a = apply_position(context.padded, affine, renormalise=False)
    renormalised = apply_position(context.padded, affine, renormalise=True)
    posed_size = (frame.width * pose.scale, frame.height * pose.scale)
    result: dict[str, Any] = {
        "pose": pose.__dict__,
        "garment_cover": garment_cover(template.mask, box),
        "displacement": displacement(direct, option_a, posed_size),
        "timings": timings,
        "designs": {},
    }
    region = crop_region(box, template.base.shape)
    for design in context.designs:
        composite_times: list[float] = []
        reference = compose(template, design, direct, composite_times)
        for _ in range(COMPOSITE_REPEATS - 1):
            compose(template, design, option_a, composite_times)
        candidate = compose(template, design, option_a, composite_times)
        renorm = compose(template, design, renormalised, [])
        metrics, delta, _ = difference(template.base, reference, candidate)
        renorm_metrics, _, _ = difference(template.base, reference, renorm)
        result["designs"][design.name] = {
            "option_a": metrics,
            "option_a_renormalised": renorm_metrics,
            "composite_seconds_median": statistics.median(composite_times),
        }
        name = f"{template.name}-{pose.name}-{design.name}.png"
        side_by_side(
            context.out / name,
            region,
            (reference, candidate, delta),
            ("direct fit", "padded + UV affine", f"dE76 0-{HEAT_RANGE:g}"),
        )
        print(
            f"  {pose.name:18s} {design.name:6s} dE mean {metrics['mean']:.2f} "
            f"p99 {metrics['p99']:.2f} tone p99 {metrics['tone_p99']:.2f} "
            f"(renorm {renorm_metrics['tone_p99']:.2f}) "
            f"shift p99 {result['displacement']['p99_px']:.2f}px",
            flush=True,
        )
    return result


def run_identity_against_published(context: Context) -> dict[str, Any]:
    """At the template's own box: the published maps (original, smaller
    evidence crop) against a direct fit and against option A, both on the
    padded-quad evidence. Separates evidence-crop effects from padding."""
    template = context.template
    published = published_maps(template)
    direct = prepare(template.base, Placement(template.box, template.mask), context.evidence).maps
    option_a = apply_position(
        context.padded,
        uv_affine(context.frame, DEFAULT_LIMITS, Pose("identity")),
        renormalise=False,
    )
    size = (context.frame.width, context.frame.height)
    results: dict[str, Any] = {
        "displacement": {
            "direct_fit_on_padded_evidence": displacement(published, direct, size),
            "option_a": displacement(published, option_a, size),
        }
    }
    for design in context.designs:
        reference = compose(template, design, published, [])
        refit = compose(template, design, direct, [])
        candidate = compose(template, design, option_a, [])
        results[design.name] = {
            "direct_fit_on_padded_evidence": difference(template.base, reference, refit)[0],
            "option_a": difference(template.base, reference, candidate)[0],
        }
        _, delta, _ = difference(template.base, reference, candidate)
        side_by_side(
            context.out / f"{template.name}-published-vs-option-a-{design.name}.png",
            crop_region(template.box, template.base.shape),
            (reference, candidate, delta),
            ("published maps", "padded + UV affine", f"dE76 0-{HEAT_RANGE:g}"),
        )
    return results


@dataclass(frozen=True)
class Args:
    workspace: Path
    out: Path
    templates: tuple[str, ...]


def parse_args() -> Args:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--template", action="append", choices=TEMPLATES)
    namespace = parser.parse_args()
    return Args(namespace.workspace, namespace.out, tuple(namespace.template or TEMPLATES))


def main() -> None:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    designs = tuple(
        Design(name, pixels, prepare_material_artwork(pixels))
        for name, pixels in (("chart", chart_design()), ("hike", real_design()))
    )
    results = [
        run_template(load_template(args.workspace, name), designs, args) for name in args.templates
    ]
    document = {
        "limits": DEFAULT_LIMITS.__dict__,
        "narrower_limits": NARROWER_LIMITS.__dict__,
        "wider_limits": WIDER_LIMITS.__dict__,
        "metric": "CIE76 dE (OpenCV float Lab, D65) over pixels either composite changed",
        "templates": results,
    }
    (args.out / "results.json").write_text(json.dumps(document, indent=2))
    print(f"wrote {args.out / 'results.json'}")


if __name__ == "__main__":
    main()
