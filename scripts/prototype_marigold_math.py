"""THROWAWAY normal-constrained geometry and deterministic photographic ink.

A7: pure ndarray math. Integer photo coordinates are pixel centres. Marigold
normals retain their camera frame (X right, Y up, Z toward viewer). Surface XYZ
uses X right, Y down, Z toward viewer, in photo-pixel units / placement width.
Orthographic visible height patches cannot infer hidden material: explicit patch
polygons carry offsets in ONE shared canonical artwork plane, plus front order.
"""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np
import prototype_surface_math as classical
from numpy.typing import NDArray

Float = NDArray[np.float32]
Pixels = NDArray[np.uint8]


def sample(field: Float, xy: Float, border: int = cv2.BORDER_REPLICATE) -> Float:
    xy = np.asarray(xy, np.float32)
    return cv2.remap(
        field,
        xy[..., 0],
        xy[..., 1],
        interpolation=cv2.INTER_LINEAR,
        borderMode=border,
        borderValue=0,
    ).astype(np.float32)


def sample_labels(labels: NDArray[np.int32], xy: Float) -> NDArray[np.int32]:
    """Labels are discrete: interpolation must never invent a third patch."""
    xy = np.asarray(xy, np.float32)
    return cv2.remap(
        labels,
        xy[..., 0],
        xy[..., 1],
        interpolation=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_REPLICATE,
    )


def resize_material(
    material: Float, labels: NDArray[np.int32], size: tuple[int, int]
) -> tuple[Float, NDArray[np.int32]]:
    """Half-pixel preview sampling confined to the frontmost source patch."""
    yy, xx = np.mgrid[: size[1], : size[0]].astype(np.float32)
    xy = np.stack(
        [
            (xx + 0.5) * labels.shape[1] / size[0] - 0.5,
            (yy + 0.5) * labels.shape[0] / size[1] - 0.5,
        ],
        -1,
    )
    target_labels = sample_labels(labels, xy)
    resized = np.zeros((*target_labels.shape, 2), np.float32)
    for label in np.unique(target_labels):
        mask = (labels == label).astype(np.float32)
        weight = sample(mask, xy)
        field = sample(material * mask[..., None], xy) / np.maximum(weight[..., None], 1e-8)
        selected = target_labels == label
        resized[selected] = field[selected]
    return resized, target_labels


def patch_derivative(material: Float, labels: NDArray[np.int32], axis: int) -> Float:
    """Centred differences inside a patch; one-sided at its boundary."""
    forward = np.roll(material, -1, axis=axis) - material
    backward = material - np.roll(material, 1, axis=axis)
    valid_forward = labels == np.roll(labels, -1, axis=axis)
    valid_backward = labels == np.roll(labels, 1, axis=axis)
    end = [slice(None), slice(None)]
    end[axis] = -1
    valid_forward[tuple(end)] = False
    end[axis] = 0
    valid_backward[tuple(end)] = False
    count = valid_forward.astype(np.float32) + valid_backward
    return (forward * valid_forward[..., None] + backward * valid_backward[..., None]) / np.maximum(
        count[..., None], 1
    )


def placement_grid(box: Float, mesh: int) -> Float:
    yy, xx = np.mgrid[:mesh, :mesh].astype(np.float32) / (mesh - 1)
    matrix = cv2.getPerspectiveTransform(
        np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32), box
    )
    return cv2.perspectiveTransform(np.stack([xx, yy], axis=-1), matrix)


def slopes(normals: Float) -> tuple[Float, Float]:
    normal = normals / np.maximum(np.linalg.norm(normals, axis=-1, keepdims=True), 1e-8)
    # One camera -> image axis conversion: dz/dx=-Nx/Nz, dz/drow=+Ny/Nz.
    valid = normal[..., 2] > 0.22
    denominator = np.maximum(normal[..., 2], 0.22)
    gradient = np.stack([-normal[..., 0] / denominator, normal[..., 1] / denominator], -1)
    return gradient.astype(np.float32), valid.astype(np.float32)


def weighted_laplace(value: NDArray, a: NDArray, b: NDArray, weight: NDArray) -> NDArray:
    delta = (value[b] - value[a]) * weight
    return np.bincount(b, weights=delta, minlength=len(value)) - np.bincount(
        a, weights=delta, minlength=len(value)
    )


def cg(
    rhs: NDArray, multiply: Callable[[NDArray], NDArray], diagonal: NDArray, initial: NDArray
) -> NDArray:
    """Small sparse PCG, no new authoring dependency in the production environment."""
    value = initial.astype(np.float64).copy()
    residual = rhs - multiply(value)
    tolerance = max(1e-9, np.linalg.norm(rhs) * 1e-7)
    preconditioned = residual / np.maximum(diagonal, 1e-10)
    direction = preconditioned.copy()
    dot = float(residual @ preconditioned)
    for _ in range(1800):
        if np.linalg.norm(residual) <= tolerance:
            return value
        product = multiply(direction)
        denominator = float(direction @ product)
        if denominator <= 1e-25:
            break
        step = dot / denominator
        value += step * direction
        residual -= step * product
        preconditioned = residual / np.maximum(diagonal, 1e-10)
        following = float(residual @ preconditioned)
        direction = preconditioned + following / max(dot, 1e-30) * direction
        dot = following
    if np.linalg.norm(rhs - multiply(value)) > max(tolerance * 20, 1e-7):
        raise ValueError(
            "Geometry solver did not converge; inspect the confidence/patch diagnostics"
        )
    return value


def integrate(
    xy: Float,
    normals: Float,
    confidence: Float,
    patch_ids: NDArray,
    depth: Float | None = None,
    depth_confidence: Float | None = None,
) -> tuple[Float, dict]:
    mesh = xy.shape[0]
    a, b, _ = classical.graph(mesh)
    p = xy.reshape(-1, 2).astype(np.float64)
    gradient, usable = slopes(normals)
    conf = (confidence * usable).ravel().astype(np.float64)
    same_patch = (patch_ids.ravel()[a] == patch_ids.ravel()[b]) & (patch_ids.ravel()[a] > 0)
    edge_weight = np.sqrt(conf[a] * conf[b]) * same_patch
    g = gradient.reshape(-1, 2)
    target = np.sum((g[a] + g[b]) * 0.5 * (p[b] - p[a]), axis=1)
    smoothing = same_patch.astype(np.float64)
    degree = np.bincount(a, weights=edge_weight, minlength=len(p)) + np.bincount(
        b, weights=edge_weight, minlength=len(p)
    )
    smooth_degree = np.bincount(a, weights=smoothing, minlength=len(p)) + np.bincount(
        b, weights=smoothing, minlength=len(p)
    )
    prior = np.full(len(p), 1e-5)
    rhs = np.bincount(b, weights=edge_weight * target, minlength=len(p)) - np.bincount(
        a, weights=edge_weight * target, minlength=len(p)
    )
    smooth_strength = 0.003

    def operator(value: NDArray) -> NDArray:
        return (
            weighted_laplace(value, a, b, edge_weight)
            + prior * value
            + smooth_strength
            * weighted_laplace(weighted_laplace(value, a, b, smoothing), a, b, smoothing)
        )

    diagonal = degree + prior + smooth_strength * (smooth_degree**2 + smooth_degree)
    z = cg(rhs, operator, diagonal, np.zeros(len(p)))
    original_weight = edge_weight.copy()
    for _ in range(3):
        residual = z[b] - z[a] - target
        selected = original_weight > 0
        threshold = (
            max(0.002, 2.5 * 1.4826 * float(np.median(np.abs(residual[selected]))))
            if selected.any()
            else 0.002
        )
        edge_weight = original_weight * np.minimum(
            1, threshold / np.maximum(np.abs(residual), 1e-8)
        )
        degree = np.bincount(a, weights=edge_weight, minlength=len(p)) + np.bincount(
            b, weights=edge_weight, minlength=len(p)
        )
        rhs = np.bincount(b, weights=edge_weight * target, minlength=len(p)) - np.bincount(
            a, weights=edge_weight * target, minlength=len(p)
        )
        diagonal = degree + prior + smooth_strength * (smooth_degree**2 + smooth_degree)
        z = cg(rhs, operator, diagonal, z)
    depth_metrics = {"used": False}
    if depth is not None:
        # Affine invariant depth increases AWAY from the viewer. Fit into the
        # same physical height frame; never add an independent arbitrary field.
        d = -depth.ravel().astype(np.float64)
        dc = np.ones_like(d) if depth_confidence is None else depth_confidence.ravel()
        dc = dc * conf
        selected = dc > 0.15
        if selected.sum() > 30 and np.std(d[selected]) > 1e-5:
            design = np.stack([d, np.ones_like(d)], axis=-1)
            weight = np.sqrt(dc[selected])
            scale, offset = np.linalg.lstsq(
                design[selected] * weight[:, None], z[selected] * weight, rcond=None
            )[0]
            # A negative fitted scale contradicts the near/far convention.
            if scale > 0:
                fitted = scale * d + offset
                prior += 0.015 * dc
                rhs += 0.015 * dc * fitted
                diagonal += 0.015 * dc
                z = cg(rhs, operator, diagonal, z)
                depth_metrics = {
                    "used": True,
                    "scale": float(scale),
                    "offset": float(offset),
                    "fit_rms": float(np.sqrt(np.mean((z[selected] - fitted[selected]) ** 2))),
                }
            else:
                depth_metrics["fallback"] = "depth scale disagrees with the normals/camera frame"
        else:
            depth_metrics["fallback"] = "insufficient confident, varying depth"
    error = z[b] - z[a] - target
    rms = np.sqrt(np.sum(edge_weight * error**2) / max(edge_weight.sum(), 1e-8))
    return np.concatenate([p, z[:, None]], axis=-1).reshape(mesh, mesh, 3).astype(np.float32), {
        "edge_slope_residual_rms": float(rms),
        "robust_downweighted_fraction": float(
            ((edge_weight < original_weight * 0.95) & (original_weight > 0)).mean()
        ),
        "grazing_fraction": float(1 - usable.mean()),
        "uncertain_fraction": float((conf < 0.15).mean()),
        "depth": depth_metrics,
        "camera": "orthographic visible height patches",
        "boundary_height": "free",
    }


def flatten(
    surface: Float, patch_ids: NDArray, anchors: list[dict] | None = None
) -> tuple[Float, dict]:
    mesh = surface.shape[0]
    a, b, _ = classical.graph(mesh)
    p = surface.reshape(-1, 3).astype(np.float64)
    rest = np.maximum(np.linalg.norm(p[b] - p[a], axis=1), 1e-8)
    edge_weight = (
        (patch_ids.ravel()[a] == patch_ids.ravel()[b]) & (patch_ids.ravel()[a] > 0)
    ).astype(np.float64)
    width = float(np.mean(np.linalg.norm(np.diff(surface[..., :2], axis=1), axis=-1).sum(axis=1)))
    height = float(np.mean(np.linalg.norm(np.diff(surface[..., :2], axis=0), axis=-1).sum(axis=0)))
    yy, xx = np.mgrid[:mesh, :mesh].astype(np.float64) / (mesh - 1)
    neutral = np.stack([xx * width, yy * height], -1).reshape(-1, 2)
    value = neutral.copy()
    prior = np.full(len(p), 0.004)
    target_prior = neutral.copy()
    degree = np.bincount(a, weights=edge_weight, minlength=len(p)) + np.bincount(
        b, weights=edge_weight, minlength=len(p)
    )

    def operator(vector: NDArray) -> NDArray:
        return weighted_laplace(vector, a, b, edge_weight) + prior * vector

    ids = patch_ids
    triangles_valid = np.stack(
        [
            (ids[:-1, :-1] == ids[:-1, 1:]) & (ids[:-1, :-1] == ids[1:, :-1]) & (ids[:-1, :-1] > 0),
            (ids[1:, 1:] == ids[:-1, 1:]) & (ids[1:, 1:] == ids[1:, :-1]) & (ids[1:, 1:] > 0),
        ],
        axis=-1,
    )
    # Existing signed_areas stacks two triangle fields, rather than interleaving them.
    selected_triangles = np.concatenate(
        [triangles_valid[..., 0].ravel(), triangles_valid[..., 1].ravel()]
    )
    barriers = 0
    for _ in range(40):
        edge = value[b] - value[a]
        target = edge * (rest / np.maximum(np.linalg.norm(edge, axis=1), 1e-8))[:, None]
        proposal = value.copy()
        for axis in range(2):
            rhs = (
                np.bincount(b, weights=edge_weight * target[:, axis], minlength=len(p))
                - np.bincount(a, weights=edge_weight * target[:, axis], minlength=len(p))
                + prior * target_prior[:, axis]
            )
            proposal[:, axis] = cg(rhs, operator, degree + prior, value[:, axis])
        step = 1.0
        while step > 1 / 1024:
            candidate = value + step * (proposal - value)
            areas = classical.signed_areas(candidate.reshape(mesh, mesh, 2).astype(np.float32))
            if not np.any(areas.ravel()[selected_triangles] <= 1e-9):
                break
            step /= 2
            barriers += 1
        if step <= 1 / 1024:
            break
        delta = float(np.max(np.abs(candidate - value)))
        value = candidate
        if delta < 1e-6:
            break
    # Placement establishes a material coordinate FRAME, not physical patch
    # boundaries. One global affine frame for all patches; never normalize
    # visible pieces into separate complete print rectangles.
    corners = np.array([0, mesh - 1, mesh * mesh - 1, mesh * (mesh - 1)])
    design = np.concatenate([value[corners], np.ones((4, 1))], axis=-1)
    frame = np.linalg.lstsq(design, neutral[corners] / [width, height], rcond=None)[0]
    uv = (
        (np.concatenate([value, np.ones((len(value), 1))], -1) @ frame)
        .reshape(mesh, mesh, 2)
        .astype(np.float32)
    )
    anchor_error = 0.0
    anchor_fraction = 1.0
    if anchors:
        # Spread corrections over cloth rather than pulling one mesh node
        # until its immediate triangles invert. One frame for every patch.
        points = np.array([anchor["location"] for anchor in anchors], np.float32)
        if np.any((points < 0) | (points > 1)):
            raise ValueError("Corrective anchors must lie inside the print placement")
        corners_xy = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32)
        locations = np.concatenate([points, corners_xy])
        desired = np.concatenate(
            [
                np.array([anchor["uv"] for anchor in anchors]),
                sample(uv, corners_xy[:, None, :] * (mesh - 1))[:, 0],
            ]
        )
        actual = sample(uv, locations[:, None, :] * (mesh - 1))[:, 0]
        squared = np.sum((locations[:, None, :] - locations[None, :, :]) ** 2, axis=-1)
        kernel = np.exp(-squared / (2 * 0.3**2))
        weights = np.linalg.solve(kernel + np.eye(len(locations)) * 1e-7, desired - actual)
        neutral_xy = np.stack([xx, yy], -1)
        dist = np.sum((neutral_xy[:, :, None, :] - locations[None, None, :, :]) ** 2, axis=-1)
        correction = (np.exp(-dist / (2 * 0.3**2)) @ weights).astype(np.float32)
        while anchor_fraction > 1 / 1024:
            candidate = uv + correction * anchor_fraction
            if not np.any(classical.signed_areas(candidate).ravel()[selected_triangles] <= 1e-9):
                break
            anchor_fraction /= 2
            barriers += 1
        if anchor_fraction > 1 / 1024:
            uv = candidate
        anchor_error = float(
            np.max(
                np.abs(sample(uv, points[:, None, :] * (mesh - 1))[:, 0] - desired[: len(points)])
            )
        )
    strain = (np.linalg.norm(value[b] - value[a], axis=1) / rest - 1)[edge_weight > 0]
    final_value = uv.reshape(-1, 2) * [width, height]
    final_strain = (np.linalg.norm(final_value[b] - final_value[a], axis=1) / rest - 1)[
        edge_weight > 0
    ]
    areas = classical.signed_areas(uv)
    return uv, {
        "rms_edge_strain": float(np.sqrt(np.mean(strain**2))) if len(strain) else 0,
        "final_frame_rms_strain": float(np.sqrt(np.mean(final_strain**2)))
        if len(final_strain)
        else 0,
        "invalid_triangles": int((areas.ravel()[selected_triangles] <= 0).sum()),
        "orientation_barrier_steps": barriers,
        "neutral_safety_blend": False,
        "max_uv_shift": float(np.max(np.linalg.norm(uv - np.stack([xx, yy], -1), axis=-1))),
        "placement_prior": 0.004,
        "material_frame_affine": frame.tolist(),
        "anchor_applied_fraction": anchor_fraction,
        "anchor_max_error": anchor_error,
        "mesh": mesh,
    }


def polygon_mask(size: tuple[int, int], points: list[list[float]]) -> Float:
    mask = np.zeros((size[1], size[0]), np.uint8)
    cv2.fillPoly(mask, [np.rint(points).astype(np.int32)], 1, lineType=cv2.LINE_8)
    return mask.astype(np.float32)


def patch_labels(size: tuple[int, int], patches: list[dict]) -> NDArray[np.int32]:
    """Listed front-to-back? Explicit order wins: larger order is FRONTMOST."""
    labels = np.ones((size[1], size[0]), np.int32)
    for index, patch in sorted(enumerate(patches), key=lambda item: item[1].get("order", 0)):
        labels[polygon_mask(size, patch["points"]) > 0] = index + 2
    return labels


def bake(
    uv: Float, box: Float, size: tuple[int, int], patches: list[dict], grid_ids: NDArray
) -> tuple[Float, Float, NDArray[np.int32]]:
    mesh = uv.shape[0]
    neutral = placement_grid(np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32), mesh)
    material, valid = classical.bake(neutral, box, size)
    labels = patch_labels(size, patches)
    xy = material * (mesh - 1)
    displacement = uv - neutral
    support = np.zeros(valid.shape, np.float32)
    for label in np.unique(labels):
        selected = (grid_ids == label).astype(np.float32)
        denominator = sample(selected, xy)
        delta = sample(displacement * selected[..., None], xy)
        pixels = labels == label
        material[pixels] += (delta / np.maximum(denominator[..., None], 1e-6))[pixels]
        support[pixels] = denominator[pixels]
        if label >= 2:
            material[pixels] += np.asarray(patches[label - 2].get("offset", [0, 0]), np.float32)
    valid *= (support > 0.05).astype(np.float32)
    labels[valid == 0] = 0
    return material, valid, labels


def lighting_fields(
    base: Pixels, shading: Float, albedo: Float, residual: Float, cloth: Float, confidence: Float
) -> tuple[dict[str, Float], dict]:
    selected = (cloth > 0.95) & (confidence > 0.35)
    if selected.sum() < 100:
        raise ValueError("Not enough confident visible cloth to normalize lighting")
    luminance = np.sum(shading * np.array([0.2126, 0.7152, 0.0722]), -1)
    exposure = max(float(np.percentile(luminance[selected], 70)), 0.01)
    iid = np.clip(shading / exposure, 0.04, 1.7).astype(np.float32)
    photo_luminance = np.sum(classical.linear(base) * [0.2126, 0.7152, 0.0722], -1).astype(
        np.float32
    )
    broad = classical.blur(photo_luminance, 3)
    photo_exposure = max(float(np.percentile(broad[selected], 70)), 0.005)
    photographic = np.repeat(np.clip(broad / photo_exposure, 0.04, 1.7)[..., None], 3, -1)
    # Keep microtexture separate from broad shading and dyed wash. Opaque ink
    # stays opaque: this changes reflectance slightly, never alpha.
    texture = np.clip((photo_luminance + 0.005) / (broad + 0.005), 0.9, 1.1)
    restrained_residual = np.clip(residual / exposure, 0, 0.035)
    reconstruction = albedo * shading + residual
    reconstruction_error = float(
        np.mean(np.abs(reconstruction[selected] - classical.linear(base)[selected]))
    )
    return {
        "iid": iid,
        "photographic": photographic.astype(np.float32),
        "texture": texture.astype(np.float32),
        "residual": restrained_residual.astype(np.float32),
    }, {
        "shading_exposure": exposure,
        "photographic_exposure": photo_exposure,
        "normalization": "70th percentile linear shading luminance on confident visible cloth",
        "blank_reconstruction_mae_linear": reconstruction_error,
        "clipped_gain_fraction": float(
            ((shading / exposure > 1.7).any(-1) & selected).sum() / selected.sum()
        ),
        "texture_range": [0.9, 1.1],
        "residual_range": [0, 0.035],
    }


def filtered_sample(
    artwork: Pixels, material: Float, patch_ids: NDArray[np.int32] | None = None
) -> Float:
    """Derivative-selected mip filtering in premultiplied linear colour."""
    packed = classical.premultiply(artwork)
    h, w = artwork.shape[:2]
    labels = np.ones(material.shape[:2], np.int32) if patch_ids is None else patch_ids
    dy, dx = (patch_derivative(material, labels, axis) for axis in (0, 1))
    du_y, dv_y = dy[..., 0], dy[..., 1]
    du_x, dv_x = dx[..., 0], dx[..., 1]
    footprint = np.maximum(np.hypot(du_x * w, dv_x * h), np.hypot(du_y * w, dv_y * h))
    levels = min(10, int(np.log2(max(2, min(h, w)))))
    lod = np.clip(np.log2(np.maximum(footprint, 1)), 0, levels)
    low = np.floor(lod).astype(int)
    fraction = lod - low
    result = np.zeros((*material.shape[:2], 4), np.float32)
    for level in range(levels + 1):
        weight = np.where(low == level, 1 - fraction, 0) + np.where(low + 1 == level, fraction, 0)
        if np.any(weight > 0):
            xy = material * np.array([packed.shape[1] - 1, packed.shape[0] - 1], np.float32)
            result += sample(packed, xy, cv2.BORDER_CONSTANT) * weight[..., None]
        if level < levels:
            packed = cv2.resize(
                packed,
                (max(1, packed.shape[1] // 2), max(1, packed.shape[0] // 2)),
                interpolation=cv2.INTER_AREA,
            )
    return result


def composite(
    base: Pixels,
    artwork: Pixels,
    material: Float,
    visibility: Float,
    gain: Float,
    texture: Float,
    residual: Float,
    texture_amount: float = 0.25,
    residual_amount: float = 0,
    patch_ids: NDArray[np.int32] | None = None,
) -> Pixels:
    sampled = filtered_sample(artwork, material, patch_ids)
    alpha = sampled[..., 3] * visibility
    ink = (
        sampled[..., :3] * gain * (1 + texture_amount * (texture - 1))[..., None]
        + sampled[..., 3, None] * residual_amount * residual
    )
    output = classical.display(
        ink * visibility[..., None] + classical.linear(base) * (1 - alpha[..., None])
    )
    output[alpha == 0] = base[alpha == 0]
    return output


@dataclass
class Calibration:
    material: Float
    visibility: Float
    patch_ids: NDArray[np.int32]
    gain: Float
    texture: Float
    residual: Float
    metadata: dict

    def identity(self) -> str:
        """Accepted numeric fields and render settings only; provenance stays separate."""
        digest = hashlib.sha256()
        for field in [
            self.material,
            self.visibility,
            self.patch_ids,
            self.gain,
            self.texture,
            self.residual,
        ]:
            digest.update(str((field.shape, str(field.dtype))).encode())
            digest.update(np.ascontiguousarray(field).tobytes())
        digest.update(json.dumps(self.metadata["render_settings"], sort_keys=True).encode())
        return digest.hexdigest()

    def dumps(self) -> bytes:
        buffer = io.BytesIO()
        np.savez_compressed(
            buffer,
            material=self.material,
            visibility=self.visibility,
            patch_ids=self.patch_ids,
            gain=self.gain,
            texture=self.texture,
            residual=self.residual,
            metadata=np.array(
                json.dumps({**self.metadata, "render_input_sha256": self.identity()})
            ),
        )
        return buffer.getvalue()

    @classmethod
    def loads(cls, payload: bytes, photo_hash: str, size: tuple[int, int]) -> Calibration:
        with np.load(io.BytesIO(payload), allow_pickle=False) as archive:
            metadata = json.loads(str(archive["metadata"]))
            if metadata.get("format") != "marigold-garment-v1":
                raise ValueError("Unsupported Marigold experimental artifact")
            if metadata.get("photo_sha256") != photo_hash:
                raise ValueError("Calibration belongs to a different blank photo")
            fields = {
                key: archive[key].copy()
                for key in ["material", "visibility", "patch_ids", "gain", "texture", "residual"]
            }
        w, h = size
        if metadata.get("size") != [w, h]:
            raise ValueError("Calibration photo dimensions do not match")
        for key, channels, bounds in [
            ("material", 2, (-4, 4)),
            ("visibility", 0, (0, 1)),
            ("gain", 3, (0.04, 1.7)),
            ("texture", 0, (0.9, 1.1)),
            ("residual", 3, (0, 0.035)),
            ("patch_ids", 0, (0, 100)),
        ]:
            field = fields[key]
            shape = (h, w, channels) if channels else (h, w)
            if (
                field.shape != shape
                or not np.isfinite(field).all()
                or field.min() < bounds[0] - 1e-6
                or field.max() > bounds[1] + 1e-6
            ):
                raise ValueError(f"Invalid calibration {key} shape, range or finiteness")
            if (key == "patch_ids" and field.dtype != np.int32) or (
                key != "patch_ids" and field.dtype != np.float32
            ):
                raise ValueError(f"Invalid calibration {key} dtype")
        calibration = cls(**fields, metadata=metadata)
        settings = metadata.get("render_settings", {})
        if set(settings) != {"texture", "residual"} or any(
            not isinstance(v, (int, float)) or not np.isfinite(v) or not 0 <= v <= 1
            for v in settings.values()
        ):
            raise ValueError("Invalid calibration render settings")
        if calibration.identity() != metadata.get("render_input_sha256"):
            raise ValueError("Calibration numeric identity does not match its fields")
        return calibration

    def render(self, base: Pixels, artwork: Pixels) -> Pixels:
        settings = self.metadata["render_settings"]
        return composite(
            base,
            artwork,
            self.material,
            self.visibility,
            self.gain,
            self.texture,
            self.residual,
            settings["texture"],
            settings["residual"],
            self.patch_ids,
        )
