"""THROWAWAY segmentation adapter: seeded GrabCut, explicitly a proposal.

Marigold has no garment segmentation. Colour seeds offer an inexpensive initial
mask; similar-coloured foreground, hair, chains and self-overlap remain ambiguous.
The review viewer retains brush corrections. Dark folds are NOT exclusion seeds.
"""

from __future__ import annotations

import cv2
import numpy as np
import prototype_surface_math as math
from numpy.typing import NDArray


def propose(base: NDArray, box: NDArray) -> tuple[NDArray, dict]:
    h, w = base.shape[:2]
    scale = min(1, 640 / max(h, w))
    small = math.resize(base, (round(w * scale), round(h * scale)))
    centre = box.mean(axis=0)
    inner = centre + (box - centre) * 0.5
    outer = centre + (box - centre) * 1.55
    seed = np.zeros(small.shape[:2], np.uint8)
    region = seed.copy()
    cv2.fillPoly(seed, [np.rint(inner * scale).astype(np.int32)], 1, lineType=cv2.LINE_8)
    cv2.fillPoly(region, [np.rint(outer * scale).astype(np.int32)], 1, lineType=cv2.LINE_8)
    lab = cv2.cvtColor(small, cv2.COLOR_RGB2LAB).astype(np.float32)
    ab = lab[..., 1:]
    values = ab[seed > 0]
    median = np.median(values, axis=0)
    deviation = np.maximum(np.median(np.abs(values - median), axis=0) * 1.4826, 4)
    distance = np.linalg.norm((ab - median) / deviation, axis=-1)
    mask = np.full(seed.shape, cv2.GC_BGD, np.uint8)
    mask[region > 0] = cv2.GC_PR_BGD
    mask[(region > 0) & (distance < 3.5)] = cv2.GC_PR_FGD
    mask[(seed > 0) & (distance < 1.7)] = cv2.GC_FGD
    # Strong chroma disagreement excludes skin on these development shirts;
    # lighting changes and dark creases alone do not supply background seeds.
    mask[(region > 0) & (distance > 5)] = cv2.GC_BGD
    if (mask == cv2.GC_FGD).sum() < 20:
        return np.ones((h, w), np.float32), {
            "adapter": "seeded GrabCut",
            "fallback": "manual visibility; too few reliable colour seeds",
        }
    cv2.setRNGSeed(2026)
    cv2.grabCut(
        small[..., ::-1].copy(),
        mask,
        None,
        np.zeros((1, 65)),
        np.zeros((1, 65)),
        3,
        cv2.GC_INIT_WITH_MASK,
    )
    cloth = ((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)).astype(np.float32)
    cloth = math.resize(cloth, (w, h))
    return cloth, {
        "adapter": "seeded GrabCut",
        "kind": "unapproved automatic colour proposal",
        "limitations": "hair, jewellery, similar-coloured foreground and cloth overlap need review",
        "seed_chroma_lab": median.tolist(),
    }
