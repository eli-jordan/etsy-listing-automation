"""Name -> id resolution. Config refers to blueprints and print providers by
name (PRD 23); this is the only place that turns one into a Printify integer id.

A print provider is named by its title -- "Monster Digital" identifies one.
A *blueprint* is not: Printify titles 706 "Unisex Garment-Dyed T-shirt", which
several brands sell, and retitles it at will. Blueprints are therefore matched
on brand + model, the pair anyone buying blanks quotes.
"""

from __future__ import annotations

import re

from etsy_listings.catalog.models import Blueprint, PrintProvider

_TRADEMARK = re.compile(r"[®™©]")
_WHITESPACE = re.compile(r"\s+")


def normalise(value: str) -> str:
    """Fold the differences nobody means: case, spacing, and the trademark
    signs Printify puts in brand names.

    Without this a hand-written ``brand: Comfort Colors`` never matches the
    catalog's ``Comfort Colors®`` -- and expecting a human to type ® into a
    YAML file to make their profile resolve is the kind of papercut that
    reads as "the tool is broken".
    """
    return _WHITESPACE.sub(" ", _TRADEMARK.sub("", value)).strip().casefold()


class CatalogResolutionError(ValueError):
    def __init__(self, kind: str, name: str, valid_names: list[str]) -> None:
        self.kind = kind
        self.name = name
        self.valid_names = valid_names
        options = ", ".join(sorted(valid_names)) or "(none available)"
        super().__init__(f"no {kind} named {name!r}. Valid names: {options}")


class AmbiguousBlueprintError(ValueError):
    """Brand and model matched more than one blueprint.

    Picking one arbitrarily would silently bind a profile to a garment nobody
    chose, so this names the candidates and stops.
    """

    def __init__(self, brand: str, model: str, candidates: list[Blueprint]) -> None:
        self.candidates = candidates
        listed = ", ".join(f"{b.title!r} (id {b.id})" for b in candidates)
        super().__init__(
            f"{brand} {model} matches more than one blueprint: {listed}. "
            f"Printify is offering two blanks under one brand and model number; "
            f"this needs a human to say which."
        )


def resolve_blueprint(brand: str, model: str, blueprints: list[Blueprint]) -> Blueprint:
    """The blueprint sold as ``brand`` ``model``.

    Title is deliberately not consulted -- see the module docstring. Both
    sides go through :func:`normalise`, so neither the catalog's ® nor a
    stray capital in a hand-written profile decides whether a garment
    resolves.
    """
    wanted = (normalise(brand), normalise(model))
    matches = [b for b in blueprints if (normalise(b.brand), normalise(b.model)) == wanted]

    if len(matches) == 1:
        return matches[0]
    if matches:
        raise AmbiguousBlueprintError(brand, model, matches)
    raise CatalogResolutionError(
        "blueprint",
        f"{brand} {model}".strip(),
        # Offered as the brand/model pairs a profile would have to name, not
        # as titles: a list of titles cannot be pasted into a `blueprint:`.
        sorted({f"{b.brand} {b.model}".strip() for b in blueprints}),
    )


def resolve_print_provider(name: str, providers: list[PrintProvider]) -> PrintProvider:
    for provider in providers:
        if provider.title == name:
            return provider
    raise CatalogResolutionError("print provider", name, [p.title for p in providers])
