"""Canonical CPU scene identities shared by previews and deployment."""

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from etsy_listings.core.render.config import MarigoldAppearance, RenderConfig
from etsy_listings.core.render.io import MARIGOLD_PNG_COMPRESSION
from etsy_listings.core.render.types import RGBA


def _canonical(document: dict[str, Any]) -> str:
    # The canonical encoding and sha256 prefix match engine.lock.canonical_hash.
    # This pure CPU module must not import the engine's orchestration package.
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def artwork_identity(artwork: RGBA) -> str:
    """Canonical decoded RGBA bytes include their shape and channel convention."""
    if artwork.ndim != 3 or artwork.shape[2] != 4 or min(artwork.shape[:2]) < 1:
        raise ValueError("Artwork identity requires a nonempty RGBA image")
    return _canonical(
        {
            "format": "rgba-u8-v1",
            "height": artwork.shape[0],
            "width": artwork.shape[1],
            "pixels": hashlib.sha256(artwork.tobytes()).hexdigest(),
        }
    )


def prepared_scene_identity(
    *,
    map_content: str,
    placement_ids: Sequence[str | None],
    artwork_digests: Sequence[str],
    photo_pixels: str,
    appearance: MarigoldAppearance,
) -> str:
    """ADR-0054: accepted map content and intentional layer order determine pixels.

    Each artwork digest comes from artwork_identity. Map content fixes target
    dimensions. Storage, runtime availability and provenance are excluded.
    """
    if len(placement_ids) != len(artwork_digests):
        raise ValueError("Artwork identity must cover every ordered placement")
    return _canonical(
        {
            "renderer": "marigold-material-v1",
            "png_compression": MARIGOLD_PNG_COMPRESSION,
            "map_content": map_content,
            "layers": [
                {"placement_id": identity, "artwork": artwork}
                for identity, artwork in zip(placement_ids, artwork_digests, strict=True)
            ],
            "photo_pixels": photo_pixels,
            "appearance": appearance.model_dump(mode="json"),
        }
    )


PHOTO_WARP_PNG_COMPRESSION = 6
"""What the render stage and full-size previews encode photo warp with."""


def photo_warp_scene_identity(
    *, photo_pixels: str, layers: Sequence[tuple[RenderConfig, str]]
) -> str:
    """A photo-warp scene's pixels: the photo's, then each painted layer's
    settings and artwork (from artwork_identity) in paint order. The derived
    height and luminance maps are functions of the photo's pixels alone.

    Bump ``renderer`` when the warp, its maps or their fixed parameters change.
    """
    return _canonical(
        {
            "renderer": "photo-warp-v1",
            "png_compression": PHOTO_WARP_PNG_COMPRESSION,
            "photo_pixels": photo_pixels,
            "layers": [
                {"render_config": json.loads(cfg.canonical_json()), "artwork": artwork}
                for cfg, artwork in layers
            ],
        }
    )
