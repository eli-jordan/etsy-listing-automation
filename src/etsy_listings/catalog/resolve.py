"""Name -> id resolution. Config refers to blueprints and print providers by
name (PRD 23); this is the only place that turns one into a Printify integer id.

A print provider is named by its title -- "Monster Digital" identifies one.
A *blueprint* is not: Printify titles 706 "Unisex Garment-Dyed T-shirt", which
several brands sell, and retitles it at will. Blueprints are therefore matched
on brand + model, the pair anyone buying blanks quotes.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from etsy_listings.catalog.models import Blueprint, PrintProvider, VariantSet
from etsy_listings.config.slug import ColourExceptions, slug_map
from etsy_listings.errors import UserFacingError

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


class CatalogResolutionError(UserFacingError, ValueError):
    def __init__(self, kind: str, name: str, valid_names: list[str]) -> None:
        self.kind = kind
        self.name = name
        self.valid_names = valid_names
        options = ", ".join(sorted(valid_names)) or "(none available)"
        super().__init__(f"no {kind} named {name!r}. Valid names: {options}")


class AmbiguousBlueprintError(UserFacingError, ValueError):
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


class UnknownSizeError(UserFacingError, ValueError):
    """A size no colour of this garment is made in.

    Distinct from a discontinued *cell* (PRD 46), which is Printify's business
    and merely reported: a size absent from the entire catalog entry is a
    profile naming something this blank does not come in, and no amount of
    skipping produces the product the user asked for.
    """

    def __init__(self, size: str, valid_sizes: list[str]) -> None:
        self.size = size
        options = ", ".join(valid_sizes) or "(none)"
        super().__init__(f"this garment is not made in size {size!r}. Sizes offered: {options}")


@dataclass(frozen=True)
class ResolvedVariant:
    """One colour × size cell, carrying the name each side of the join uses.

    ``colour`` is Printify's own (``"Blue Jean"``), ``colour_slug`` is what the
    listing and the mockup filenames say (``"blue-jean"``). Both, because
    re-deriving either at a call site is how the two drift apart.
    """

    id: int
    colour: str
    colour_slug: str
    size: str


@dataclass(frozen=True)
class VariantResolution:
    variants: tuple[ResolvedVariant, ...]
    missing: tuple[tuple[str, str], ...]
    """``(colour_slug, size)`` cells the catalog does not offer. Reported, not
    fatal -- PRD 46."""

    def ids(self, *, colours: Collection[str] | None = None) -> tuple[int, ...]:
        """Variant ids, optionally narrowed to some colour slugs.

        ``print_areas.*.variant_ids`` wants ids and nothing else, and the
        narrowing is what PRD 30's on-light/on-dark split needs to partition
        one product's variants across two print areas.
        """
        return tuple(v.id for v in self.variants if colours is None or v.colour_slug in colours)


def resolve_variants(
    variant_set: VariantSet,
    colour_slugs: Sequence[str],
    sizes: Sequence[str],
    exceptions: ColourExceptions,
) -> VariantResolution:
    """The variant ids for ``colour_slugs`` × ``sizes``, in that order.

    Order is the listing's colours outer, the profile's sizes inner, so the
    payload reads like the config it came from and a diff of it is legible.

    Three failure modes, and they are deliberately not the same shape:

    - a colour slug matching nothing is a typo -- fatal, listing the slugs
      that do exist;
    - a size no colour offers is a profile naming a size this blank is not
      made in -- fatal;
    - a single colour × size cell the catalog has dropped is Printify's doing
      -- reported in :attr:`VariantResolution.missing` and skipped (PRD 46).
    """
    by_slug = {slug: name for name, slug in slug_map(variant_set.colors, exceptions).items()}

    unknown = [slug for slug in colour_slugs if slug not in by_slug]
    if unknown:
        raise CatalogResolutionError("colour", unknown[0], sorted(by_slug))

    offered_sizes = {v.options.size for v in variant_set.variants}
    for size in sizes:
        if size not in offered_sizes:
            raise UnknownSizeError(size, sorted(offered_sizes))

    by_cell = {(v.options.color, v.options.size): v for v in variant_set.variants}

    resolved: list[ResolvedVariant] = []
    missing: list[tuple[str, str]] = []
    for slug in colour_slugs:
        colour = by_slug[slug]
        for size in sizes:
            variant = by_cell.get((colour, size))
            if variant is None:
                missing.append((slug, size))
                continue
            resolved.append(
                ResolvedVariant(id=variant.id, colour=colour, colour_slug=slug, size=size)
            )

    return VariantResolution(variants=tuple(resolved), missing=tuple(missing))
