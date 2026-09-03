"""Pure logic behind the ``new`` picker (PRD 19): everything that doesn't touch
a terminal, so it's testable through the fake catalog client with no
interactive prompting -- ``newcmd/interactive.py`` is a thin wrapper around
this that only adds the questionary prompts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from etsy_listings.catalog.models import Blueprint, VariantSet
from etsy_listings.config.errors import format_validation_error
from etsy_listings.config.exceptions import load_exceptions
from etsy_listings.config.listing import GENERATE, Listing
from etsy_listings.config.profile import PrintArea, Profile
from etsy_listings.config.slug import ColourExceptions, SlugCollisionError, slug_map, slugify
from etsy_listings.workspace.workspace import Workspace

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "tshirt": ("t-shirt", "tee", "shirt"),
}
"""PRD: the catalog endpoint exposes no category facet, so filtering is
client-side keyword matching over title/brand/model -- flagged in the PRD as
something to verify for a better mechanism; unchanged here (risk 7)."""

SIZE_ORDER = ["XS", "S", "M", "L", "XL", "XXL", "XXXL", "4XL", "5XL"]


def filter_blueprints_by_category(blueprints: list[Blueprint], category: str) -> list[Blueprint]:
    keywords = CATEGORY_KEYWORDS.get(category, (category,))
    keywords_lower = tuple(kw.lower() for kw in keywords)

    def matches(blueprint: Blueprint) -> bool:
        haystack = f"{blueprint.title} {blueprint.brand} {blueprint.model}".lower()
        return any(keyword in haystack for keyword in keywords_lower)

    return [b for b in blueprints if matches(b)]


def sort_sizes(sizes: set[str]) -> list[str]:
    known = [s for s in SIZE_ORDER if s in sizes]
    unknown = sorted(sizes - set(SIZE_ORDER))
    return known + unknown


def resolve_colour_slugs(variant_set: VariantSet, exceptions: ColourExceptions) -> dict[str, str]:
    """Colour name -> slug, applying exceptions.yaml and raising on collision
    (PRD: "new reports any collisions it finds while building a profile")."""
    return slug_map(variant_set.colors, exceptions)


def profile_slug_for(blueprint: Blueprint) -> str:
    return slugify(blueprint.title)


def build_profile(
    *,
    blueprint_title: str,
    provider_title: str,
    placeholder: str,
    variant_set: VariantSet,
    mockup_template: str,
) -> Profile:
    area = variant_set.placeholder(placeholder)
    if area is None:
        available = ", ".join(p.position for p in variant_set.placeholders) or "(none)"
        raise ValueError(
            f"blueprint {blueprint_title!r} / provider {provider_title!r} has no "
            f"{placeholder!r} placeholder. Available: {available}"
        )
    sizes = sort_sizes({v.options.size for v in variant_set.variants})
    return Profile(
        blueprint=blueprint_title,
        print_provider=provider_title,
        placeholder=placeholder,
        print_area=PrintArea(width=area.width, height=area.height),
        sizes=sizes,
        mockup_template=mockup_template,
    )


def write_profile_if_absent(workspace: Workspace, slug: str, profile: Profile) -> bool:
    """Returns True if a new profile.yaml was written, False if one already
    existed and was left untouched (PRD: "writes profiles/{slug}.yaml if
    absent; reuses it silently if present")."""
    path = workspace.root / "profiles" / f"{slug}.yaml"
    if path.is_file():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(profile.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    return True


def build_listing_stub(
    *,
    profile_slug: str,
    design_ref: str,
    colours: list[str],
    sizes: list[str],
    base_price: str,
    brief: str,
) -> dict[str, Any]:
    """A starting ``listing.yaml`` document: one price per size (all equal --
    per-size and per-colour adjustment is a manual edit, PRD step 2), one
    ``mockup:`` media entry per colour, and ``<generate>`` sentinels for the
    fields AI copy generation owns."""
    return {
        "profile": profile_slug,
        "design": design_ref,
        "colors": colours,
        "brief": brief,
        "prices": {size: base_price for size in sizes},
        "etsy": {"title": GENERATE, "description": GENERATE, "tags": GENERATE, "materials": []},
        "media": [{"mockup": colour} for colour in colours],
    }


def validate_listing_stub(data: dict[str, Any], *, currency: str) -> Listing:
    try:
        return Listing.model_validate(data, context={"currency": currency})
    except ValidationError as exc:
        raise format_validation_error(Path("<new listing stub>"), exc) from exc


def write_listing(workspace: Workspace, design_name: str, data: dict[str, Any]) -> Path:
    path = workspace.root / "listings" / design_name / "listing.yaml"
    if path.is_file():
        raise FileExistsError(f"a listing already exists at {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def load_workspace_exceptions(workspace: Workspace) -> ColourExceptions:
    return load_exceptions(workspace.root / "exceptions.yaml")


__all__ = [
    "CATEGORY_KEYWORDS",
    "SIZE_ORDER",
    "SlugCollisionError",
    "build_listing_stub",
    "build_profile",
    "filter_blueprints_by_category",
    "load_workspace_exceptions",
    "profile_slug_for",
    "resolve_colour_slugs",
    "sort_sizes",
    "validate_listing_stub",
    "write_listing",
    "write_profile_if_absent",
]
