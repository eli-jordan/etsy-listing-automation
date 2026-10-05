"""Internal robust normal/depth integration and metric fitting. ADR-0053.

Camera normals X right/Y up/Z viewer become image X right/Y down/Z viewer.
No experimental anchors or overlap controls are exposed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import cv2
import numpy as np
from numpy.typing import NDArray

from etsy_listings.core.render import _material_math as surface_math

Float = NDArray[np.float32]
Pixels = NDArray[np.uint8]


def sample(field: Float, xy: Float, border: int = cv2.BORDER_REPLICATE) -> Float:
    xy = np.asarray(xy, np.float32)
    return cast(
        Float,
        cv2.remap(
            field,
            xy[..., 0],
            xy[..., 1],
            interpolation=cv2.INTER_LINEAR,
            borderMode=border,
            borderValue=(0,),
        ).astype(np.float32),
    )


def placement_grid(box: Float, mesh: int) -> Float:
    yy, xx = np.mgrid[:mesh, :mesh].astype(np.float32) / (mesh - 1)
    matrix = cv2.getPerspectiveTransform(
        np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32), box
    )
    return cast(Float, cv2.perspectiveTransform(np.stack([xx, yy], axis=-1), matrix))


def slopes(normals: Float) -> tuple[Float, Float]:
    normal = normals / np.maximum(np.linalg.norm(normals, axis=-1, keepdims=True), 1e-8)
    # One camera -> image axis conversion: dz/dx=-Nx/Nz, dz/drow=+Ny/Nz.
    valid = normal[..., 2] > 0.22
    denominator = np.maximum(normal[..., 2], 0.22)
    gradient = np.stack([-normal[..., 0] / denominator, normal[..., 1] / denominator], -1)
    return gradient.astype(np.float32), valid.astype(np.float32)


def weighted_laplace(
    value: NDArray[Any], a: NDArray[Any], b: NDArray[Any], weight: NDArray[Any]
) -> NDArray[Any]:
    delta = (value[b] - value[a]) * weight
    return np.bincount(b, weights=delta, minlength=len(value)) - np.bincount(
        a, weights=delta, minlength=len(value)
    )


def cg(
    rhs: NDArray[Any],
    multiply: Callable[[NDArray[Any]], NDArray[Any]],
    diagonal: NDArray[Any],
    initial: NDArray[Any],
) -> NDArray[Any]:
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
    patch_ids: NDArray[Any],
    depth: Float | None = None,
    depth_confidence: Float | None = None,
) -> tuple[Float, dict[str, Any]]:
    mesh = xy.shape[0]
    a, b, _ = surface_math.graph(mesh)
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

    def operator(value: NDArray[Any]) -> NDArray[Any]:
        return np.asarray(
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
    depth_metrics: dict[str, Any] = {"used": False}
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
    surface: Float,
    patch_ids: NDArray[Any],
) -> tuple[Float, dict[str, Any]]:
    mesh = surface.shape[0]
    a, b, _ = surface_math.graph(mesh)
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

    def operator(vector: NDArray[Any]) -> NDArray[Any]:
        return np.asarray(weighted_laplace(vector, a, b, edge_weight) + prior * vector)

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
            areas = surface_math.signed_areas(candidate.reshape(mesh, mesh, 2).astype(np.float32))
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
    strain = (np.linalg.norm(value[b] - value[a], axis=1) / rest - 1)[edge_weight > 0]
    final_value = uv.reshape(-1, 2) * [width, height]
    final_strain = (np.linalg.norm(final_value[b] - final_value[a], axis=1) / rest - 1)[
        edge_weight > 0
    ]
    areas = surface_math.signed_areas(uv)
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
    cv2.fillPoly(mask, [np.rint(points).astype(np.int32)], (1,), lineType=cv2.LINE_8)
    return mask.astype(np.float32)


def lighting_fields(
    base: Pixels, shading: Float, albedo: Float, residual: Float, cloth: Float, confidence: Float
) -> tuple[dict[str, Float], dict[str, Any]]:
    selected = (cloth > 0.95) & (confidence > 0.35)
    if selected.sum() < 100:
        raise ValueError("Not enough confident visible cloth to normalize lighting")
    luminance = np.sum(shading * np.array([0.2126, 0.7152, 0.0722]), -1)
    exposure = max(float(np.percentile(luminance[selected], 70)), 0.01)
    iid = np.clip(shading / exposure, 0.04, 1.7).astype(np.float32)
    photo_luminance = np.sum(surface_math.linear(base) * [0.2126, 0.7152, 0.0722], -1).astype(
        np.float32
    )
    broad = surface_math.blur(photo_luminance, 3)
    photo_exposure = max(float(np.percentile(broad[selected], 70)), 0.005)
    photographic = np.repeat(np.clip(broad / photo_exposure, 0.04, 1.7)[..., None], 3, -1)
    # Keep microtexture separate from broad shading and dyed wash. Opaque ink
    # stays opaque: this changes reflectance slightly, never alpha.
    texture = np.clip((photo_luminance + 0.005) / (broad + 0.005), 0.9, 1.1)
    restrained_residual = np.clip(residual / exposure, 0, 0.035)
    reconstruction = albedo * shading + residual
    reconstruction_error = float(
        np.mean(np.abs(reconstruction[selected] - surface_math.linear(base)[selected]))
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
