"""Pure logic behind the ``new`` picker (PRD 19): everything that doesn't touch
a terminal, so it's testable through the fake catalog client with no
interactive prompting -- ``newcmd/interactive.py`` only sequences the
questions, and ``newcmd/prompts.py`` picks a backend that can actually drive
the terminal it was given.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import ValidationError

from etsy_listings.catalog.models import Blueprint, VariantSet
from etsy_listings.config.errors import ConfigLoadError, format_validation_error
from etsy_listings.config.listing import GENERATE, MAX_MEDIA_ENTRIES, Listing
from etsy_listings.config.profile import PrintArea, Profile
from etsy_listings.config.slug import ColourExceptions, slug_map, slugify
from etsy_listings.render.config import load_template_config
from etsy_listings.workspace.workspace import Workspace

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "tshirt": ("t-shirt", "tee", "shirt"),
}
"""PRD: the catalog endpoint exposes no category facet, so filtering is
client-side keyword matching over title/brand/model -- flagged in the PRD as
something to verify for a better mechanism; unchanged here (risk 7)."""

SIZE_ORDER = ["XS", "S", "M", "L", "XL", "XXL", "2XL", "XXXL", "3XL", "4XL", "5XL", "6XL"]
"""Both spellings of the big sizes, adjacent, because Printify uses the
numeric one. Comfort Colors 1717 / Monster Digital sells ``2XL``/``3XL``, and
with only ``XXL``/``XXXL`` listed here they fell through to the alphabetical
"unknown" tail while ``4XL`` sorted normally -- producing
``S M L XL 4XL 2XL 3XL`` in the profile `new` wrote."""


def filter_blueprints_by_category(blueprints: list[Blueprint], category: str) -> list[Blueprint]:
    keywords = CATEGORY_KEYWORDS.get(category, (category,))
    keywords_lower = tuple(kw.lower() for kw in keywords)

    def matches(blueprint: Blueprint) -> bool:
        haystack = f"{blueprint.title} {blueprint.brand} {blueprint.model}".lower()
        return any(keyword in haystack for keyword in keywords_lower)

    return [b for b in blueprints if matches(b)]


# ----------------------------------------------------------------------
# The garment picker's rows.
#
# Printify offers hundreds of blueprints and `--category tshirt` still leaves
# dozens, so the rows are columned -- marker, brand, model, title -- and the
# ones this workspace already has a profile for sort to the top. Building them
# lives here rather than in the prompt so it can be tested without a terminal,
# the same reason every other decision in `new` does. Filtering, on a terminal
# that can do it at all, is fzf's job -- see `newcmd/prompts.py`.
# ----------------------------------------------------------------------

LOCAL_MARKER = "⭐"
LOCAL_MARKER_FALLBACK = "* "
"""Two terminal columns either way -- ``⭐`` is East Asian Wide, so it occupies
the same width as the two-character ASCII fallback and the marker column stays
aligned on a terminal that cannot print it."""

MARKER_WIDTH = 2


@dataclass(frozen=True)
class BlueprintChoice:
    """One row of the garment picker."""

    blueprint: Blueprint
    is_local: bool
    label: str


def local_blueprint_titles(workspace: Workspace) -> set[str]:
    """Blueprint titles this workspace already has a profile for.

    A profile that will not parse is skipped rather than fatal: it makes a row
    lose its marker, and refusing to open the picker over an unrelated broken
    file would be a poor trade.
    """
    titles: set[str] = set()
    for name in workspace.profile_names():
        try:
            titles.add(workspace.load_profile(name).blueprint)
        except (ConfigLoadError, ValidationError):
            continue
    return titles


def build_blueprint_choices(
    blueprints: list[Blueprint],
    local_titles: set[str],
    *,
    marker: str = LOCAL_MARKER,
) -> list[BlueprintChoice]:
    """Blueprints as aligned ``marker  brand  model  title`` rows.

    Brand and model are what identify a garment to anyone who buys blanks --
    "Gildan 18500" is the thing you look up, while Printify's titles bury it
    ("Unisex Pullover Hoodie" is sold under half a dozen brands). Garments
    this workspace already has a profile for come first and carry the marker:
    in practice a shop reuses a handful of blueprints over and over, and
    having to re-find the one used yesterday is the picker failing at its most
    common job. Within each group, rows sort by brand then title, so the brand
    column reads as blocks rather than as noise.
    """
    entries = [(blueprint, blueprint.title in local_titles) for blueprint in blueprints]
    entries.sort(key=lambda entry: (not entry[1], entry[0].brand.lower(), entry[0].title.lower()))

    brand_width = max((len(b.brand) for b, _ in entries), default=0)
    model_width = max((len(b.model) for b, _ in entries), default=0)

    return [
        BlueprintChoice(
            blueprint=blueprint,
            is_local=is_local,
            label=(
                f"{(marker if is_local else ' ' * MARKER_WIDTH)}  "
                f"{blueprint.brand.ljust(brand_width)}  "
                f"{blueprint.model.ljust(model_width)}  "
                f"{blueprint.title}"
            ),
        )
        for blueprint, is_local in entries
    ]


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
    colour_tone: dict[str, Literal["light", "dark"]] | None = None,
) -> Profile:
    area = variant_set.placeholder(placeholder)
    if area is None:
        available = ", ".join(variant_set.positions()) or "(none)"
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
        colour_tone=colour_tone or {},
    )


def write_profile_if_absent(workspace: Workspace, slug: str, profile: Profile) -> bool:
    """Returns True if a new profile.yaml was written, False if one already
    existed and was left untouched (PRD: "writes profiles/{slug}.yaml if
    absent; reuses it silently if present")."""
    path = workspace.profile_file(slug)
    if path.is_file():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(profile.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    return True


def load_template_kind(workspace: Workspace, template: str) -> str:
    """Which of the three kinds ``template`` is (`A11`).

    ``new`` has to know: the shape of a valid ``media`` entry depends on it,
    and writing the wrong shape produces a listing that only fails later, at
    render time, with nothing pointing back at ``new``.
    """
    path = workspace.template_config_file(template)
    if not path.is_file():
        raise ConfigLoadError(path, "template config not found -- calibrate it with `ui` first")
    return load_template_config(yaml.safe_load(path.read_text(encoding="utf-8"))).kind


def build_media_entries(*, template: str, kind: str, colours: list[str]) -> list[dict[str, str]]:
    """The stub's ``media:``, which depends on the referenced template's kind.

    ``colour-matrix`` gets one entry per colour, each naming its colour --
    but capped at Etsy's 10-image limit, because a print provider can offer
    far more colours than Etsy accepts photos: Comfort Colors 1717 / Monster
    Digital offers 33, and one entry each is a listing Etsy will reject.
    Which 10 is genuinely arbitrary, so it is the first 10 in offer order and
    ``new`` says that it truncated. Every colour still appears in ``colors:``
    -- that decides which Printify variants sell, not which photos get
    rendered (PRD 31).

    ``multiple`` and ``single`` get exactly one entry and **no** ``colour``:
    each produces one output, so there is nothing to disambiguate (PRD 28).
    """
    if kind == "colour-matrix":
        return [{"template": template, "colour": colour} for colour in colours[:MAX_MEDIA_ENTRIES]]
    return [{"template": template}]


def build_listing_stub(
    *,
    profile_slug: str,
    design_ref: str,
    colours: list[str],
    sizes: list[str],
    base_price: str,
    brief: str,
    media: list[dict[str, str]],
) -> dict[str, Any]:
    """A starting ``listing.yaml`` document: one price per size (all equal --
    per-size and per-colour adjustment is a manual edit, PRD step 2), the
    media entries :func:`build_media_entries` decided, and ``<generate>``
    sentinels for the fields AI copy generation owns."""
    return {
        "profile": profile_slug,
        "design": design_ref,
        "colors": colours,
        "brief": brief,
        "prices": dict.fromkeys(sizes, base_price),
        "etsy": {"title": GENERATE, "description": GENERATE, "tags": GENERATE, "materials": []},
        "media": media,
    }


def validate_listing_stub(data: dict[str, Any], *, currency: str) -> Listing:
    try:
        return Listing.model_validate(data, context={"currency": currency})
    except ValidationError as exc:
        raise format_validation_error(Path("<new listing stub>"), exc) from exc


def write_listing(workspace: Workspace, design_name: str, data: dict[str, Any]) -> Path:
    path = workspace.listing_file(design_name)
    if path.is_file():
        raise FileExistsError(f"a listing already exists at {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path
