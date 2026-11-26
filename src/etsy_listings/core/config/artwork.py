from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

Tone = Literal["light", "dark"]

DesignMap = Mapping[str, str | None]
"""``Listing.design``: reserved base keys (``default``, ``on-light``,
``on-dark``) and colour exceptions, key -> workspace-rooted ref. Only the two
tone keys may hold ``None`` -- a light/dark slot not filled yet."""

DEFAULT: Final = "default"
ON_LIGHT: Final = "on-light"
ON_DARK: Final = "on-dark"
BASE_KEYS: Final = (DEFAULT, ON_LIGHT, ON_DARK)
"""Also :func:`representative`'s order."""
TONE_KEYS: Final[dict[Tone, str]] = {"light": ON_LIGHT, "dark": ON_DARK}


@dataclass(frozen=True)
class Resolved:
    ref: str
    source: Literal["colour", "default", "on-light", "on-dark"]


@dataclass(frozen=True)
class SlotEmpty:
    """Light/dark mode, and the colour's tone slot is ``None`` or absent."""

    tone: Tone


@dataclass(frozen=True)
class Unclassified:
    """Light/dark mode, and the garment profile gives this colour no tone."""

    colour: str


@dataclass(frozen=True)
class NeedsColour:
    """Light/dark mode, and the scene names no colour to pick a slot by."""


@dataclass(frozen=True)
class NoDesign:
    """Neither ``default`` nor a tone key: nothing has been chosen."""


Resolution = Resolved | SlotEmpty | Unclassified | NeedsColour | NoDesign


def is_light_dark(design: DesignMap) -> bool:
    """Light/dark mode is recorded by the presence of a tone *key*, ``None``
    included -- that is how an empty pair survives a reload."""
    return ON_LIGHT in design or ON_DARK in design


def resolve(design: DesignMap, colour: str | None, tones: Mapping[str, Tone]) -> Resolution:
    if colour is not None:
        own = design.get(colour)
        if own is not None:
            return Resolved(own, "colour")
    if is_light_dark(design):
        return _resolve_by_tone(design, colour, tones)
    default = design.get(DEFAULT)
    if default is None:
        return NoDesign()
    return Resolved(default, "default")


def _resolve_by_tone(
    design: DesignMap, colour: str | None, tones: Mapping[str, Tone]
) -> Resolution:
    if colour is None:
        return NeedsColour()
    tone = tones.get(colour)
    if tone is None:
        return Unclassified(colour)
    ref = design.get(TONE_KEYS[tone])
    if ref is None:
        return SlotEmpty(tone)
    return Resolved(ref, "on-light" if tone == "light" else "on-dark")


def representative(design: DesignMap) -> str | None:
    for key in BASE_KEYS:
        ref = design.get(key)
        if ref is not None:
            return ref
    return None


def slot_users(
    design: DesignMap, enabled: Sequence[str], tones: Mapping[str, Tone]
) -> dict[Tone, list[str]]:
    """The enabled *automatic* colours of each tone, in enabled order.

    A colour with its own design leaves the base-slot calculation, and an
    unclassified one is in neither list -- it is blocked for its own reason.
    Drives the missing-slot blocker and the one-slot warning.
    """
    users: dict[Tone, list[str]] = {"light": [], "dark": []}
    for colour in enabled:
        if design.get(colour) is not None:
            continue
        tone = tones.get(colour)
        if tone is not None:
            users[tone].append(colour)
    return users
