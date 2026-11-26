"""Name -> id resolution: the only place a config name for a blueprint or print
provider becomes a Printify integer id."""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from difflib import get_close_matches

from etsy_listings.core.clients.printify.models import Blueprint, PrintProvider, Variant, VariantSet
from etsy_listings.core.config.slug import ColourExceptions, slug_map
from etsy_listings.core.errors import UserFacingError

_TRADEMARK = re.compile(r"[®™©]")
_WHITESPACE = re.compile(r"\s+")
_LIST_EVERY_NAME_UP_TO = 8
_CLOSEST_NAMES_LISTED_BEYOND_THAT = 5
_BLUEPRINT_BRAND_ALIASES = {"comfort colors print on demand": "comfort colors"}
"""Known catalog renames only; never match unrelated brands by similarity (ADR-0005)."""


def normalise(value: str) -> str:
    """Fold case, spacing and the trademark signs Printify puts in brand names."""
    return _WHITESPACE.sub(" ", _TRADEMARK.sub("", value)).strip().casefold()


class CatalogResolutionError(UserFacingError, ValueError):
    def __init__(self, kind: str, name: str, valid_names: list[str]) -> None:
        self.kind = kind
        self.name = name
        self.valid_names = valid_names
        if len(valid_names) > _LIST_EVERY_NAME_UP_TO:
            closest = get_close_matches(
                name, sorted(valid_names), n=_CLOSEST_NAMES_LISTED_BEYOND_THAT, cutoff=0.0
            )
            options = ", ".join(closest)
            suggestions = f"Closest names: {options} (and {len(valid_names) - len(closest)} more)"
        else:
            options = ", ".join(sorted(valid_names)) or "(none available)"
            suggestions = f"Valid names: {options}"
        super().__init__(f"no {kind} named {name!r}. {suggestions}")


class AmbiguousBlueprintError(UserFacingError, ValueError):
    def __init__(self, brand: str, model: str, candidates: list[Blueprint]) -> None:
        self.candidates = candidates
        listed = ", ".join(f"{b.title!r} (id {b.id})" for b in candidates)
        super().__init__(
            f"{brand} {model} matches more than one blueprint: {listed}. "
            f"Printify is offering two blanks under one brand and model number; "
            f"this needs a human to say which."
        )


def _blueprint_brand(brand: str) -> str:
    normalised = normalise(brand)
    return _BLUEPRINT_BRAND_ALIASES.get(normalised, normalised)


def resolve_blueprint(brand: str, model: str, blueprints: list[Blueprint]) -> Blueprint:
    wanted = (_blueprint_brand(brand), normalise(model))
    matches = [b for b in blueprints if (_blueprint_brand(b.brand), normalise(b.model)) == wanted]

    if len(matches) == 1:
        return matches[0]
    if matches:
        raise AmbiguousBlueprintError(brand, model, matches)
    raise CatalogResolutionError(
        "blueprint",
        f"{brand} {model}".strip(),
        sorted({f"{b.brand} {b.model}".strip() for b in blueprints}),
    )


def resolve_print_provider(name: str, providers: list[PrintProvider]) -> PrintProvider:
    for provider in providers:
        if provider.title == name:
            return provider
    raise CatalogResolutionError("print provider", name, [p.title for p in providers])


class UnknownSizeError(UserFacingError, ValueError):
    """A size no colour of this garment is made in (unlike a missing cell, fatal)."""

    def __init__(self, size: str, valid_sizes: list[str]) -> None:
        self.size = size
        options = ", ".join(valid_sizes) or "(none)"
        super().__init__(f"this garment is not made in size {size!r}. Sizes offered: {options}")


@dataclass(frozen=True)
class ResolvedVariant:
    """One colour × size cell: Printify's ``colour`` (``"Blue Jean"``) and the
    listing's ``colour_slug`` (``"blue-jean"``)."""

    id: int
    colour: str
    colour_slug: str
    size: str


@dataclass(frozen=True)
class VariantResolution:
    variants: tuple[ResolvedVariant, ...]
    missing: tuple[tuple[str, str], ...]
    """``(colour_slug, size)`` cells the catalog does not offer. Reported, not
    fatal -- missing variant cells."""

    def ids(self, *, colours: Collection[str] | None = None) -> tuple[int, ...]:
        return tuple(v.id for v in self.variants if colours is None or v.colour_slug in colours)


def resolve_variants(
    variant_set: VariantSet,
    colour_slugs: Sequence[str],
    sizes: Sequence[str],
    exceptions: ColourExceptions,
) -> VariantResolution:
    """The variant ids for ``colour_slugs`` × ``sizes``, colours outer. An
    unknown colour or size is fatal; a cell the catalog dropped is reported in
    :attr:`VariantResolution.missing`."""
    by_slug = {slug: name for name, slug in slug_map(variant_set.colors, exceptions).items()}

    unknown = [slug for slug in colour_slugs if slug not in by_slug]
    if unknown:
        raise CatalogResolutionError("colour", unknown[0], sorted(by_slug))

    _check_sizes(variant_set, sizes)
    by_cell = {(v.options.color, v.options.size): v for v in variant_set.variants}
    return _resolve_cells(
        [(slug, by_slug[slug], size) for slug in colour_slugs for size in sizes], by_cell
    )


def _check_sizes(variant_set: VariantSet, sizes: Sequence[str]) -> None:
    offered_sizes = {v.options.size for v in variant_set.variants}
    for size in sizes:
        if size not in offered_sizes:
            raise UnknownSizeError(size, sorted(offered_sizes))


def _resolve_cells(
    cells: list[tuple[str, str, str]], by_cell: Mapping[tuple[str, str], Variant]
) -> VariantResolution:
    resolved: list[ResolvedVariant] = []
    missing: list[tuple[str, str]] = []
    for slug, colour, size in cells:
        variant = by_cell.get((colour, size))
        if variant is None:
            missing.append((slug, size))
            continue
        resolved.append(ResolvedVariant(id=variant.id, colour=colour, colour_slug=slug, size=size))
    return VariantResolution(variants=tuple(resolved), missing=tuple(missing))
