"""Where a listing-shaped document names a mockup template.

A template's name is its directory, and a document refers to it by that name
in three places: ``media[].template``, ``etsy.variation_images`` and the keys
of ``template_positions``. Listings, listing templates and the frozen copies
batches keep all share that shape, so one function follows a rename through
any of them. It reads raw mappings, not models, because a document with some
unrelated problem still has to follow.
"""

from __future__ import annotations

import copy
from typing import Any


def rename_template_refs(document: dict[str, Any], old: str, new: str) -> dict[str, Any] | None:
    """``document`` with every reference to template ``old`` naming ``new``,
    as a copy, or ``None`` when it does not refer to ``old``."""
    renamed = copy.deepcopy(document)
    _rename_media(renamed, old, new)
    _rename_variation_images(renamed, old, new)
    _rename_positions(renamed, old, new)
    return None if renamed == document else renamed


def _rename_media(document: dict[str, Any], old: str, new: str) -> None:
    media = document.get("media")
    if not isinstance(media, list):
        return
    for entry in media:
        if isinstance(entry, dict) and entry.get("template") == old:
            entry["template"] = new


def _rename_variation_images(document: dict[str, Any], old: str, new: str) -> None:
    etsy = document.get("etsy")
    if isinstance(etsy, dict) and etsy.get("variation_images") == old:
        etsy["variation_images"] = new


def _rename_positions(document: dict[str, Any], old: str, new: str) -> None:
    positions = document.get("template_positions")
    if isinstance(positions, dict) and old in positions:
        document["template_positions"] = {
            (new if key == old else key): value for key, value in positions.items()
        }
