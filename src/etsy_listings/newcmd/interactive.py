"""The ``new`` picker's interactive shell (PRD 19). Thin by design -- every
decision it makes is delegated to :mod:`etsy_listings.newcmd.logic`, which is
what the behaviour tests exercise through a fake catalog. This module only
adds the questionary prompts and is not itself unit-tested, the same as
``auth``'s real OAuth flow won't be -- there's nothing to assert about a
terminal prompt except that a human can answer it.
"""

from __future__ import annotations

import questionary
import typer

from etsy_listings.catalog.client import CatalogClient
from etsy_listings.newcmd.logic import (
    SlugCollisionError,
    build_listing_stub,
    build_profile,
    filter_blueprints_by_category,
    load_workspace_exceptions,
    profile_slug_for,
    resolve_colour_slugs,
    validate_listing_stub,
    write_listing,
    write_profile_if_absent,
)
from etsy_listings.workspace.workspace import Workspace

DEFAULT_PLACEHOLDER = "front"


def run_new(workspace: Workspace, catalog: CatalogClient, design_name: str, category: str) -> None:
    blueprints = filter_blueprints_by_category(catalog.blueprints(), category)
    if not blueprints:
        typer.echo(f"no blueprints match category {category!r}", err=True)
        raise typer.Exit(code=1)

    blueprint_choice = questionary.select(
        "Garment:", choices=[f"{b.title} ({b.brand})" for b in blueprints]
    ).ask()
    if blueprint_choice is None:
        raise typer.Exit(code=1)
    blueprint = blueprints[[f"{b.title} ({b.brand})" for b in blueprints].index(blueprint_choice)]

    providers = catalog.print_providers(blueprint.id)
    if not providers:
        typer.echo(f"no print providers offer {blueprint.title!r}", err=True)
        raise typer.Exit(code=1)
    preferred = workspace.defaults.preferred_print_provider
    default_title = preferred if preferred in {p.title for p in providers} else providers[0].title
    provider_choice = questionary.select(
        "Print provider:", choices=[p.title for p in providers], default=default_title
    ).ask()
    if provider_choice is None:
        raise typer.Exit(code=1)
    provider = next(p for p in providers if p.title == provider_choice)

    variant_set = catalog.variants(blueprint.id, provider.id)
    exceptions = load_workspace_exceptions(workspace)
    try:
        colour_slugs = resolve_colour_slugs(variant_set, exceptions)
    except SlugCollisionError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    mockup_template = questionary.text("Mockup template set:", default="flat-lay-01").ask()
    if not mockup_template:
        raise typer.Exit(code=1)

    profile = build_profile(
        blueprint_title=blueprint.title,
        provider_title=provider.title,
        placeholder=DEFAULT_PLACEHOLDER,
        variant_set=variant_set,
        mockup_template=mockup_template,
    )
    slug = profile_slug_for(blueprint)
    written = write_profile_if_absent(workspace, slug, profile)
    typer.echo(f"{'wrote' if written else 'reusing existing'} profiles/{slug}.yaml")

    base_price = questionary.text(
        f"Starting price per size, {workspace.defaults.currency} (edit per-size later):",
        default="0",
    ).ask()
    if base_price is None:
        raise typer.Exit(code=1)

    colours = sorted(colour_slugs.values())
    listing_data = build_listing_stub(
        profile_slug=slug,
        design_ref=f"../../designs/{design_name}.png",
        colours=colours,
        sizes=profile.sizes,
        base_price=f"{base_price} {workspace.defaults.currency}",
        brief="",
    )
    validate_listing_stub(listing_data, currency=workspace.defaults.currency)
    path = write_listing(workspace, design_name, listing_data)
    typer.echo(f"wrote {path}")
