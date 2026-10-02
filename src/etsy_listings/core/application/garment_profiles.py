"""Garment profiles: which catalog blueprints a workspace sells, and the
profile ``new`` records for one.

Filtering the catalog by category, keying a blueprint by brand and model,
sorting sizes, slugging colours, and recording a profile the first time a
garment is used -- reusing it, hand edits and all, every time after. The
wizard that asks which garment is the CLI's (``cli/new.py``); everything
here is tested through the fake catalog client with no terminal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import yaml
from pydantic import ValidationError

from etsy_listings.core.clients.printify.models import Blueprint, PrintProvider, VariantSet
from etsy_listings.core.clients.printify.resolve import normalise
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.config.garment_profile import BlueprintRef, GarmentProfile, PrintArea
from etsy_listings.core.config.slug import ColourExceptions, slug_map, slugify
from etsy_listings.core.workspace.workspace import Workspace

DEFAULT_PLACEHOLDER = "front"
"""The print area a new garment profile records."""

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "tshirt": ("t-shirt", "tee", "shirt"),
}
"""The catalog endpoint exposes no category facet, so filtering is
client-side keyword matching over title/brand/model."""

SIZE_ORDER = ["XS", "S", "M", "L", "XL", "XXL", "2XL", "XXXL", "3XL", "4XL", "5XL", "6XL"]
"""Both spellings of the big sizes, adjacent, because Printify uses the
numeric one. Comfort Colors 1717 / Monster Digital sells ``2XL``/``3XL``, and
with only ``XXL``/``XXXL`` listed here they fell through to the alphabetical
"unknown" tail while ``4XL`` sorted normally -- producing
``S M L XL 4XL 2XL 3XL`` in the garment profile `new` wrote."""


def filter_blueprints_by_category(blueprints: list[Blueprint], category: str) -> list[Blueprint]:
    keywords = CATEGORY_KEYWORDS.get(category, (category,))
    keywords_lower = tuple(kw.lower() for kw in keywords)

    def matches(blueprint: Blueprint) -> bool:
        haystack = f"{blueprint.title} {blueprint.brand} {blueprint.model}".lower()
        return any(keyword in haystack for keyword in keywords_lower)

    return [b for b in blueprints if matches(b)]


def local_blueprint_keys(workspace: Workspace) -> set[tuple[str, str]]:
    """The ``(brand, model)`` pairs this workspace already has a garment
    profile for, normalised for comparison.

    Keyed on brand+model rather than title, because that is what a garment
    profile now identifies a blueprint by -- and it is what makes
    the marker survive Printify retitling a garment.

    A garment profile that will not parse is skipped rather than fatal: it
    costs a row its marker, and refusing to open the picker over one
    unrelated broken file would be a poor trade.
    """
    keys: set[tuple[str, str]] = set()
    for name in workspace.garment_profile_names():
        try:
            ref = workspace.load_garment_profile(name).blueprint
        except (ConfigLoadError, ValidationError):
            continue
        keys.add((normalise(ref.brand), normalise(ref.model)))
    return keys


def sort_sizes(sizes: set[str]) -> list[str]:
    known = [s for s in SIZE_ORDER if s in sizes]
    unknown = sorted(sizes - set(SIZE_ORDER))
    return known + unknown


def resolve_colour_slugs(variant_set: VariantSet, exceptions: ColourExceptions) -> dict[str, str]:
    """Colour name -> slug, applying exceptions.yaml and raising on collision."""
    return slug_map(variant_set.colors, exceptions)


def garment_profile_slug_for(blueprint: Blueprint) -> str:
    """``garment-profiles/{slug}.yaml``, from brand and model.

    Not from the title: Printify's is generic, so a title slug would file the
    Comfort Colors 1717 under ``unisex-garment-dyed-t-shirt.yaml`` alongside
    every other brand's version of the same shirt. Brand and model give
    ``comfort-colors-1717`` -- the name the docs have always shown, and one
    that survives a retitle.
    """
    return slugify(f"{blueprint.brand} {blueprint.model}")


def blueprint_ref(blueprint: Blueprint) -> BlueprintRef:
    """The catalog entry as a garment profile records it.

    Brand and model are written verbatim, ® and all, because that is what the
    catalog says; resolution normalises both sides, so a human editing the
    file afterwards need not reproduce the symbol.
    """
    return BlueprintRef(brand=blueprint.brand, model=blueprint.model, title=blueprint.title)


def build_garment_profile(
    *,
    blueprint: Blueprint,
    provider_title: str,
    placeholder: str,
    variant_set: VariantSet,
    colors: dict[str, Literal["light", "dark"]] | None = None,
) -> GarmentProfile:
    ref = blueprint_ref(blueprint)
    area = variant_set.placeholder(placeholder)
    if area is None:
        available = ", ".join(variant_set.positions()) or "(none)"
        raise ValueError(
            f"blueprint {str(ref)!r} / provider {provider_title!r} has no "
            f"{placeholder!r} placeholder. Available: {available}"
        )
    sizes = sort_sizes({v.options.size for v in variant_set.variants})
    return GarmentProfile(
        blueprint=ref,
        print_provider=provider_title,
        placeholder=placeholder,
        print_area=PrintArea(width=area.width, height=area.height),
        sizes=sizes,
        colors=colors or {},
    )


def write_garment_profile_if_absent(
    workspace: Workspace, slug: str, garment_profile: GarmentProfile
) -> bool:
    """Returns True if a new garment profile was written, False if one already
    existed and was left untouched."""
    path = workspace.garment_profile_file(slug)
    if path.is_file():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(garment_profile.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    return True


@dataclass(frozen=True)
class SavedGarmentProfile:
    slug: str
    profile: GarmentProfile
    """What is on disk now: the new profile, or the existing one as edited."""
    written: bool


def ensure_garment_profile(
    workspace: Workspace,
    blueprint: Blueprint,
    provider: PrintProvider,
    variant_set: VariantSet,
    *,
    placeholder: str = DEFAULT_PLACEHOLDER,
) -> SavedGarmentProfile:
    """The garment profile for ``blueprint``, recorded if this is its first use.

    An existing profile is never overwritten and is read back as it stands,
    so hand edits since it was written -- a trimmed colour list -- carry into
    every listing made from it. Raises ``ValueError`` when the provider offers
    no ``placeholder`` print area.
    """
    built = build_garment_profile(
        blueprint=blueprint,
        provider_title=provider.title,
        placeholder=placeholder,
        variant_set=variant_set,
    )
    slug = garment_profile_slug_for(blueprint)
    written = write_garment_profile_if_absent(workspace, slug, built)
    profile = built if written else workspace.load_garment_profile(slug)
    return SavedGarmentProfile(slug=slug, profile=profile, written=written)


def listing_colours(profile: GarmentProfile, colour_slugs: dict[str, str]) -> list[str]:
    """The colours a new listing sells: whatever the garment profile lists --
    reflecting any hand editing since it was written -- else every catalog
    colour, the first time a garment is used."""
    if profile.colors:
        return sorted(profile.colors)
    return sorted(colour_slugs.values())
