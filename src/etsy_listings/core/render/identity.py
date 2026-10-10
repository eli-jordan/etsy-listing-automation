"""Canonical CPU scene identities shared by previews and deployment."""

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from etsy_listings.core.render.config import MarigoldAppearance
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
    """ADR-0053: accepted map content and intentional layer order determine pixels.

    Each artwork digest comes from artwork_identity. Map content fixes target
    dimensions. Storage, runtime availability and provenance are excluded.
    """
    if len(placement_ids) != len(artwork_digests):
        raise ValueError("Artwork identity must cover every ordered placement")
    return _canonical(
        {
            "renderer": "marigold-material-v1",
            "map_content": map_content,
            "layers": [
                {"placement_id": identity, "artwork": artwork}
                for identity, artwork in zip(placement_ids, artwork_digests, strict=True)
            ],
            "photo_pixels": photo_pixels,
            "appearance": appearance.model_dump(mode="json"),
        }
    )
