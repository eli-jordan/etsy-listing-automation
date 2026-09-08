"""Colour slugification: PRD 7a.

A mockup filename must equal the slugified Printify colour name (``"Blue Jean"``
-> ``blue-jean.png``), and ``listing.yaml`` refers to colours by that same slug.
The rules here are the stable, single source of truth for that mapping. A sparse,
empty-by-default ``exceptions.yaml`` overrides names that don't slugify cleanly
(ampersands, slashes, parenthesised names) or that collide on one slug.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from pydantic import RootModel

from etsy_listings.errors import UserFacingError

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Lowercase, collapse runs of non-alphanumerics to a single hyphen, trim."""
    lowered = name.strip().lower()
    slug = _NON_ALNUM.sub("-", lowered).strip("-")
    return slug


class ColourExceptions(RootModel[dict[str, str]]):
    """``exceptions.yaml``: colour name -> explicit slug override. Empty by default."""

    root: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.root.get(name)


@dataclass(frozen=True)
class SlugCollision:
    slug: str
    names: tuple[str, ...]


class SlugCollisionError(UserFacingError, ValueError):
    def __init__(self, collisions: list[SlugCollision]) -> None:
        self.collisions = collisions
        lines = [f"  '{c.slug}' <- {', '.join(sorted(c.names))}" for c in collisions]
        super().__init__(
            "colour names collide on the same slug; add entries to exceptions.yaml "
            "to disambiguate:\n" + "\n".join(lines)
        )


def slug_map(names: list[str], exceptions: ColourExceptions) -> dict[str, str]:
    """Map each colour name to its slug, applying ``exceptions`` overrides first.

    Raises :class:`SlugCollisionError` if two distinct names resolve to the same
    slug, naming every offending slug and its colliding names in one error.
    """
    result: dict[str, str] = {}
    by_slug: dict[str, list[str]] = defaultdict(list)
    for name in names:
        slug = exceptions.get(name) or slugify(name)
        result[name] = slug
        by_slug[slug].append(name)

    collisions = [
        SlugCollision(slug=slug, names=tuple(collided))
        for slug, collided in by_slug.items()
        if len(collided) > 1
    ]
    if collisions:
        raise SlugCollisionError(collisions)
    return result
