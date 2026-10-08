from __future__ import annotations

import numpy as np
import pytest

from etsy_listings.core.preparation.numerics import EvidenceIdentity, evidence_covers, plan_crop


def test_crop_expands_each_side_rounds_outward_and_records_pixel_transform() -> None:
    box = np.array([[10.5, 20.25], [30.5, 20.25], [30.5, 40.25], [10.5, 40.25]], np.float32)
    crop = plan_crop(box, (50, 50))
    assert crop.rectangle == (2, 12, 39, 49)
    assert crop.photo_size == (50, 50)
    assert crop.prediction_size == (37, 37)
    assert crop.photo_to_prediction == (1.0, 1.0, -2.0, -12.0)
    assert plan_crop(box, (32, 35)).rectangle == (2, 12, 32, 35)


def test_evidence_reuse_requires_exact_identity_and_the_full_clipped_margin() -> None:
    box = np.array([[10, 10], [30, 10], [30, 30], [10, 30]], np.float32)
    identity = EvidenceIdentity("photo-a", "checkpoints-a", "inference-a", "crop-v1")
    crop = plan_crop(box, (50, 50))
    assert evidence_covers(crop, identity, box, (50, 50), identity)
    moved = box + [1, 0]
    assert not evidence_covers(crop, identity, moved, (50, 50), identity)
    changed = EvidenceIdentity("photo-b", "checkpoints-a", "inference-a", "crop-v1")
    assert not evidence_covers(crop, identity, box, (50, 50), changed)
    boundary_box = box - [10, 10]
    clipped = plan_crop(boundary_box, (20, 20))
    assert evidence_covers(clipped, identity, boundary_box, (20, 20), identity)


def test_flat_cloth_preparation_bakes_pixel_centres_and_the_saved_mask() -> None:
    from etsy_listings.core.preparation.numerics import Evidence, prepare

    size = (64, 64)
    box = np.array([[10, 10], [53, 10], [53, 53], [10, 53]], np.float32)
    normals = np.zeros((64, 64, 3), np.float32)
    normals[..., 2] = 1
    evidence = Evidence(
        plan_crop(box, size),
        EvidenceIdentity("photo", "models", "settings", "crop-v1"),
        normals,
        np.full((64, 64, 3), 0.5, np.float32),
        np.full((64, 64, 3), 0.4, np.float32),
        np.zeros((64, 64, 3), np.float32),
        np.full((64, 64), 0.5, np.float32),
    )
    mask = np.ones((64, 64), np.float32)
    mask[30:35, 30:35] = 0
    phases = []
    result = prepare(
        np.full((64, 64, 3), 128, np.uint8), box, evidence, mask=mask, checkpoint=phases.append
    )
    np.testing.assert_allclose(result.maps.material[10, 10], [0, 0], atol=1e-6)
    np.testing.assert_allclose(result.maps.material[53, 53], [1, 1], atol=1e-6)
    assert result.maps.visibility[32, 32] == 0
    assert result.maps.visibility[20, 20] == 1
    assert result.maps.visibility[0, 0] == 0
    assert phases == ["fitting", "flattening", "baking", "lighting"]
    assert result.maps.material.dtype == np.float32
    assert result.diagnostics["depth"]["used"] is False


def test_automatic_mask_proposes_cloth_and_excludes_background_deterministically() -> None:
    from etsy_listings.core.preparation.numerics import propose_mask

    base = np.full((96, 96, 3), [40, 150, 40], np.uint8)
    base[20:76, 20:76] = [170, 40, 40]
    box = np.array([[30, 30], [65, 30], [65, 65], [30, 65]], np.float32)
    proposal = propose_mask(base, box)
    assert proposal.mask[45, 45] == 1
    assert proposal.mask[0, 0] == 0
    np.testing.assert_array_equal(propose_mask(base, box).mask, proposal.mask)
    assert proposal.algorithm == "seeded-grabcut-v1"


def test_prediction_resize_and_padding_preserve_half_pixel_photo_centres() -> None:
    from etsy_listings.core.preparation.numerics import Crop

    crop = Crop((10, 20, 30, 30), (50, 50), (20, 10), (1, 1, -10, -20))
    resized = crop.resized((42, 22), padding=(1, 1, 1, 1))
    assert resized.rectangle == crop.rectangle
    assert resized.prediction_size == (42, 22)
    assert resized.photo_to_prediction == (2, 2, -18.5, -38.5)
    assert resized.padding == (1, 1, 1, 1)


def test_folded_normals_and_depth_fit_a_nonplanar_material_field() -> None:
    from etsy_listings.core.preparation.numerics import Evidence, prepare

    yy, xx = np.mgrid[:64, :64].astype(np.float32)
    slope = 0.6 * np.cos(xx / 64 * 2 * np.pi)
    normals = np.stack([-slope, np.zeros_like(slope), np.ones_like(slope)], -1)
    normals /= np.linalg.norm(normals, axis=-1, keepdims=True)
    depth = (0.5 - 0.4 * np.sin(xx / 64 * 2 * np.pi)).astype(np.float32)
    box = np.array([[10, 10], [53, 10], [53, 53], [10, 53]], np.float32)
    evidence = Evidence(
        plan_crop(box, (64, 64)),
        EvidenceIdentity("p", "m", "i", "v"),
        normals,
        np.full((64, 64, 3), 0.5, np.float32),
        np.full((64, 64, 3), 0.4, np.float32),
        np.zeros((64, 64, 3), np.float32),
        depth,
    )
    result = prepare(
        np.full((64, 64, 3), 128, np.uint8), box, evidence, mask=np.ones((64, 64), np.float32)
    )
    assert result.diagnostics["depth"]["used"] is True
    assert result.diagnostics["invalid_triangles"] == 0
    assert result.diagnostics["max_uv_shift"] > 0.005
    assert np.isfinite(result.maps.material).all()


def test_cpu_cancellation_stops_at_the_requested_phase_without_baking() -> None:
    from etsy_listings.core.preparation.numerics import Evidence, prepare

    box = np.array([[10, 10], [53, 10], [53, 53], [10, 53]], np.float32)
    normals = np.zeros((64, 64, 3), np.float32)
    normals[..., 2] = 1
    evidence = Evidence(
        plan_crop(box, (64, 64)),
        EvidenceIdentity("p", "m", "i", "v"),
        normals,
        np.ones((64, 64, 3), np.float32),
        np.ones((64, 64, 3), np.float32),
        np.zeros((64, 64, 3), np.float32),
        np.ones((64, 64), np.float32),
    )
    phases = []

    def cancel(phase):
        phases.append(phase)
        if phase == "flattening":
            raise InterruptedError("cancel")

    with pytest.raises(InterruptedError, match="cancel"):
        prepare(
            np.full((64, 64, 3), 128, np.uint8),
            box,
            evidence,
            mask=np.ones((64, 64), np.float32),
            checkpoint=cancel,
        )
    assert phases == ["fitting", "flattening"]


@pytest.mark.parametrize(
    "box,size",
    [
        (np.zeros((4, 2), np.float32), (50, 50)),
        (np.full((4, 2), np.nan, np.float32), (50, 50)),
        (np.array([[100, 100], [120, 100], [120, 120], [100, 120]], np.float32), (50, 50)),
    ],
)
def test_crop_refuses_degenerate_nonfinite_or_outside_placements(box, size) -> None:
    with pytest.raises(ValueError):
        plan_crop(box, size)
