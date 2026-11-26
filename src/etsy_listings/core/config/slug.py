from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from pydantic import RootModel

from etsy_listings.core.errors import RefusedError

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    lowered = name.strip().lower()
    return _NON_ALNUM.sub("-", lowered).strip("-")


class ColourExceptions(RootModel[dict[str, str]]):
    root: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.root.get(name)


@dataclass(frozen=True)
class SlugCollision:
    slug: str
    names: tuple[str, ...]


class SlugCollisionError(RefusedError):
    def __init__(self, collisions: list[SlugCollision]) -> None:
        self.collisions = collisions
        lines = [f"  '{c.slug}' <- {', '.join(sorted(c.names))}" for c in collisions]
        super().__init__(
            "colour names collide on the same slug; add entries to exceptions.yaml "
            "to disambiguate:\n" + "\n".join(lines)
        )


def slug_map(names: list[str], exceptions: ColourExceptions) -> dict[str, str]:
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
