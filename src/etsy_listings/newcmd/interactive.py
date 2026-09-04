"""The ``new`` picker's interactive shell (PRD 19). Thin by design -- every
decision it makes is delegated to :mod:`etsy_listings.newcmd.logic`, which is
what the behaviour tests exercise through a fake catalog. This module only
sequences the questions; *how* a question gets asked is
:mod:`etsy_listings.newcmd.prompts`, which picks a backend that can actually
drive the terminal it was given (questionary cannot, under cygwin).
"""

from __future__ import annotations

from typing import Literal, cast

import typer

from etsy_listings.catalog.client import CatalogClient
from etsy_listings.catalog.models import Blueprint, PrintProvider, VariantSet
from etsy_listings.cli import glyphs
from etsy_listings.config.listing import MAX_MEDIA_ENTRIES
from etsy_listings.config.slug import SlugCollisionError
from etsy_listings.newcmd import prompts
from etsy_listings.newcmd.logic import (
    LOCAL_MARKER,
    LOCAL_MARKER_FALLBACK,
    build_blueprint_choices,
    build_listing_stub,
    build_media_entries,
    build_profile,
    filter_blueprints_by_category,
    load_template_kind,
    local_blueprint_titles,
    profile_slug_for,
    resolve_colour_slugs,
    validate_listing_stub,
    write_listing,
    write_profile_if_absent,
)
from etsy_listings.workspace.workspace import Workspace

DEFAULT_PLACEHOLDER = "front"


def _cancelled() -> typer.Exit:
    return typer.Exit(code=1)


def _pick_blueprint(workspace: Workspace, blueprints: list[Blueprint]) -> Blueprint:
    """Pick from ``marker  brand  model  title`` rows.

    Even ``--category tshirt`` leaves dozens of blueprints, and Printify's
    titles bury the useful word in the middle ("Unisex Garment-Dyed Heavy
    Weight Tee"), so a scrolling list is the wrong instrument. Garments this
    workspace already has a profile for sort to the top and carry a marker: a
    shop reuses a handful of blueprints, and re-finding the one used yesterday
    is this picker's most common job.
    """
    marker = glyphs.choose(LOCAL_MARKER, LOCAL_MARKER_FALLBACK)
    choices = build_blueprint_choices(blueprints, local_blueprint_titles(workspace), marker=marker)
    by_label = {choice.label: choice for choice in choices}

    answer = prompts.choose(
        "Garment",
        list(by_label),
        marker_hint=f"{marker.strip()} = already used in this workspace",
    )
    if answer is None:
        raise _cancelled()
    return by_label[answer].blueprint


def _pick_provider(workspace: Workspace, providers: list[PrintProvider]) -> PrintProvider:
    """The shop's ``preferred_print_provider`` sorts first when it is offered,
    so the common case is the first row rather than a default the fuzzy
    backends have no way to express."""
    preferred = workspace.defaults.preferred_print_provider
    ordered = sorted(providers, key=lambda p: (p.title != preferred, p.title.lower()))
    by_title = {p.title: p for p in ordered}

    answer = prompts.choose("Print provider", list(by_title))
    if answer is None:
        raise _cancelled()
    return by_title[answer]


def _report_print_area_choice(variant_set: VariantSet) -> None:
    """Say so when the profile's print area is one of several on offer.

    Printify's print areas are per-variant and genuinely differ by garment
    size. The profile carries exactly one (PRD 8a), so `new` records the
    largest -- a defensible default, but not one worth making silently, since
    it decides how big the design file has to be.
    """
    sizes = variant_set.placeholder_sizes(DEFAULT_PLACEHOLDER)
    if len(sizes) < 2:
        return
    largest, smallest = sizes[0], sizes[-1]
    typer.echo(
        f"{DEFAULT_PLACEHOLDER} print area varies by garment size: {len(sizes)} sizes, "
        f"{smallest.width}x{smallest.height} to {largest.width}x{largest.height}. "
        f"Recording the largest."
    )


def _pick_template(workspace: Workspace) -> str:
    """Pick from the templates that exist, rather than typing a name.

    A typo used to be accepted silently and produce a listing that failed
    much later at render time, with nothing pointing back at `new`. Reading
    the template is not optional anyway -- its kind decides the shape of a
    valid `media` entry (`A11`) -- so it may as well be picked from the list.
    """
    names = workspace.template_names()
    if not names:
        typer.echo(
            f"no calibrated mockup templates under {workspace.templates_dir()}.\n"
            f"  Build one with `etsy-listings ui` before creating a listing.",
            err=True,
        )
        raise typer.Exit(code=1)
    answer = prompts.choose("Mockup template set", names)
    if answer is None:
        raise _cancelled()
    return answer


def _report_media_choice(
    template: str, kind: str, colours: list[str], media: list[dict[str, str]]
) -> None:
    """Say what got a photo and what did not.

    Both branches are surprising in silence: a `single`/`multiple` template
    renders one image no matter how many colours sell, and a `colour-matrix`
    one has to stop at Etsy's 10-image limit while the listing still sells
    every colour.
    """
    if kind != "colour-matrix":
        typer.echo(
            f"{template} is a {kind}-kind template: one image for the listing, "
            f"covering all {len(colours)} colours."
        )
        return
    if len(media) < len(colours):
        typer.echo(
            f"{len(colours)} colours offered, but Etsy allows {MAX_MEDIA_ENTRIES} images: "
            f"media covers the first {len(media)}. All {len(colours)} stay in colors: "
            f"(they decide which variants sell) -- edit media: to choose which get photos."
        )


def _warn_if_design_missing(workspace: Workspace, design_name: str) -> None:
    """A warning, not an error: writing the listing before the artwork exists
    is a legitimate order to work in. But ``new`` derives the path from the
    argument without ever looking, so a name that does not match the file on
    disk -- ``duke-java-developer.png`` saved as ``duke-java-developer.png.png``
    is the easy way to get there -- surfaces much later as a render failure
    about a file the user believes they created.
    """
    path = workspace.design_file(design_name)
    if path.is_file():
        return
    near = sorted(p.name for p in path.parent.glob(f"{design_name}*") if p.is_file())
    hint = f" Did you mean {near[0]!r}?" if near else ""
    typer.echo(f"note: {path} does not exist yet.{hint}")


def run_new(workspace: Workspace, catalog: CatalogClient, design_name: str, category: str) -> None:
    _warn_if_design_missing(workspace, design_name)
    blueprints = filter_blueprints_by_category(catalog.blueprints(), category)
    if not blueprints:
        typer.echo(f"no blueprints match category {category!r}", err=True)
        raise typer.Exit(code=1)

    blueprint = _pick_blueprint(workspace, blueprints)

    providers = catalog.print_providers(blueprint.id)
    if not providers:
        typer.echo(f"no print providers offer {blueprint.title!r}", err=True)
        raise typer.Exit(code=1)
    provider = _pick_provider(workspace, providers)

    variant_set = catalog.variants(blueprint.id, provider.id)
    _report_print_area_choice(variant_set)
    exceptions = workspace.load_exceptions()
    try:
        colour_slugs = resolve_colour_slugs(variant_set, exceptions)
    except SlugCollisionError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    mockup_template = _pick_template(workspace)
    template_kind = load_template_kind(workspace, mockup_template)

    colour_tone: dict[str, Literal["light", "dark"]] = {}
    needs_tone = prompts.confirm(
        "Will any listing on this profile need different artwork for light vs dark shirts?",
        default=False,
    )
    if needs_tone is None:
        raise _cancelled()
    if needs_tone:
        for colour in sorted(colour_slugs.values()):
            tone = prompts.choose(f"{colour}: light or dark garment?", ["light", "dark"])
            if tone is None:
                raise _cancelled()
            colour_tone[colour] = cast('Literal["light", "dark"]', tone)

    profile = build_profile(
        blueprint_title=blueprint.title,
        provider_title=provider.title,
        placeholder=DEFAULT_PLACEHOLDER,
        variant_set=variant_set,
        colour_tone=colour_tone,
    )
    slug = profile_slug_for(blueprint)
    written = write_profile_if_absent(workspace, slug, profile)
    typer.echo(f"{'wrote' if written else 'reusing existing'} profiles/{slug}.yaml")

    base_price = prompts.text(
        f"Starting price per size, {workspace.defaults.currency} (edit per-size later):",
        default="0",
    )
    if base_price is None:
        raise _cancelled()

    colours = sorted(colour_slugs.values())
    media = build_media_entries(template=mockup_template, kind=template_kind, colours=colours)
    _report_media_choice(mockup_template, template_kind, colours, media)
    listing_data = build_listing_stub(
        profile_slug=slug,
        design_ref=f"../../designs/{design_name}.png",
        colours=colours,
        sizes=profile.sizes,
        base_price=f"{base_price} {workspace.defaults.currency}",
        brief="",
        media=media,
    )
    validate_listing_stub(listing_data, currency=workspace.defaults.currency)
    path = write_listing(workspace, design_name, listing_data)
    typer.echo(f"wrote {path}")
