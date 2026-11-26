from __future__ import annotations

from pathlib import Path

import typer

from etsy_listings.cli import prompts, terminal
from etsy_listings.cli.pickers import (
    CREATE_NEW_PLAN_LABEL,
    LOCAL_MARKER,
    LOCAL_MARKER_FALLBACK,
    Choice,
    build_blueprint_choices,
    build_design_choices,
    build_pricing_plan_choices,
)
from etsy_listings.core.application.garment_profiles import (
    DEFAULT_PLACEHOLDER,
    ensure_garment_profile,
    filter_blueprints_by_category,
    listing_colours,
    local_blueprint_keys,
    resolve_colour_slugs,
)
from etsy_listings.core.application.listing_creation import (
    ListingStub,
    build_media_entries,
    load_template_kind,
    validate_listing_stub,
)
from etsy_listings.core.application.pricing_plans import (
    GarmentOffer,
    PriceSources,
    create_starting_pricing_plan,
    load_candidate_pricing_plans,
)
from etsy_listings.core.application.pricing_plans import pricing_plan_ref as make_pricing_plan_ref
from etsy_listings.core.clients.printify.models import Blueprint, PrintProvider, VariantSet
from etsy_listings.core.clients.printify.protocol import CatalogClient
from etsy_listings.core.config.media import MAX_IMAGES
from etsy_listings.core.config.slug import SlugCollisionError
from etsy_listings.core.workspace.listing_documents import ListingDocuments
from etsy_listings.core.workspace.workspace import Workspace

MIN_SIZES_TO_COMPARE = 2


def _pick_blueprint(workspace: Workspace, blueprints: list[Blueprint]) -> Blueprint:
    marker = terminal.choose(LOCAL_MARKER, LOCAL_MARKER_FALLBACK)
    choices = build_blueprint_choices(blueprints, local_blueprint_keys(workspace), marker=marker)
    return prompts.pick(
        "Garment",
        choices,
        label=lambda choice: choice.label,
        marker_hint=f"{marker.strip()} = already used in this workspace",
    ).value


def _pick_provider(workspace: Workspace, providers: list[PrintProvider]) -> PrintProvider:
    """The shop's ``preferred_print_provider`` sorts first: the fuzzy backends
    have no way to express a default."""
    preferred = workspace.defaults.printify.preferred_print_provider
    ordered = sorted(providers, key=lambda p: (p.title != preferred, p.title.lower()))
    return prompts.pick("Print provider", ordered, label=lambda provider: provider.title)


def _report_print_area_choice(variant_set: VariantSet) -> None:
    """Say so when the garment profile's print area is one of several on offer.

    Printify's print areas differ by garment size and the profile records
    only the largest, which decides how big the design file has to be.
    """
    sizes = variant_set.placeholder_sizes(DEFAULT_PLACEHOLDER)
    if len(sizes) < MIN_SIZES_TO_COMPARE:
        return
    largest, smallest = sizes[0], sizes[-1]
    typer.echo(
        f"{DEFAULT_PLACEHOLDER} print area varies by garment size: {len(sizes)} sizes, "
        f"{smallest.width}x{smallest.height} to {largest.width}x{largest.height}. "
        f"Recording the largest."
    )


def _pick_design(workspace: Workspace) -> str:
    """Pick the design from what is in ``designs/``, newest first.

    The ``new`` argument still works, for scripting and for naming artwork
    that does not exist yet.
    """
    choices = build_design_choices(workspace.design_files(), set(workspace.listing_names()))
    if not choices:
        typer.echo(
            f"no designs under {workspace.designs_dir()}.\n"
            f"  Put the artwork there as <name>.png, or pass a name: "
            f"`etsy-listings new <design>`.",
            err=True,
        )
        raise typer.Exit(code=1)
    return prompts.pick(
        "Design", choices, label=lambda choice: choice.label, marker_hint="newest first"
    ).value.stem


def _pick_template(workspace: Workspace) -> str:
    names = workspace.template_names()
    if not names:
        typer.echo(
            f"no calibrated mockup templates under {workspace.templates_dir()}.\n"
            f"  Build one with `etsy-listings ui` before creating a listing.",
            err=True,
        )
        raise typer.Exit(code=1)
    return prompts.ask_choice("Mockup template set", names)


def _report_media_choice(
    template: str, kind: str, colours: list[str], media: list[dict[str, str]]
) -> None:
    """Say what got a photo and what did not."""
    if kind != "colour-matrix":
        typer.echo(
            f"{template} is a {kind}-kind template: one image for the listing, "
            f"covering all {len(colours)} colours."
        )
        return
    if len(media) < len(colours):
        typer.echo(
            f"{len(colours)} colours offered, but Etsy allows {MAX_IMAGES} images: "
            f"media covers the first {len(media)}. All {len(colours)} stay in colors: "
            f"(they decide which variants sell) -- edit media: to choose which get photos."
        )


def _warn_if_design_missing(workspace: Workspace, design_name: str) -> None:
    """Warn, and name a near miss such as ``<name>.png.png``."""
    path = workspace.design_file(design_name)
    if path.is_file():
        return
    near = [p.name for p in workspace.design_files() if p.name.startswith(design_name)]
    hint = f" Did you mean {near[0]!r}?" if near else ""
    typer.echo(f"note: {path} does not exist yet.{hint}")


def _pick_or_create_pricing_plan(
    workspace: Workspace, catalog: CatalogClient, offer: GarmentOffer
) -> Path:
    candidates = load_candidate_pricing_plans(workspace)
    rows: list[Choice[Path | None]] = [
        *build_pricing_plan_choices(candidates, offer.garment_profile_slug),
        Choice(value=None, label=CREATE_NEW_PLAN_LABEL),
    ]

    marker = terminal.choose(LOCAL_MARKER, LOCAL_MARKER_FALLBACK)
    answer = prompts.pick(
        "Pricing plan",
        rows,
        label=lambda row: row.label,
        marker_hint=f"{marker.strip()} = sizes match this garment exactly",
    ).value

    if answer is None:
        name = prompts.ask_text("Pricing plan name:")
        created = create_starting_pricing_plan(
            workspace, PriceSources(catalog), name=name, offer=offer
        )
        typer.echo(f"wrote {created.path}")
        if not created.complete:
            typer.echo(
                "  note: some prices could not be computed from live Printify/FX data "
                "-- see the comment at the top of the file for what fell back to 0."
            )
        return created.path

    return answer


def _reject_existing_listing(workspace: Workspace, design_name: str) -> None:
    """Refuse a taken name before the wizard asks anything."""
    if not ListingDocuments(workspace).is_free(design_name):
        typer.echo(f"a listing already exists at {workspace.listing_dir(design_name)}", err=True)
        raise typer.Exit(code=1)


def run_new(
    workspace: Workspace, catalog: CatalogClient, design_name: str | None, category: str
) -> None:
    if design_name is None:
        design_name = _pick_design(workspace)
    else:
        _warn_if_design_missing(workspace, design_name)
    _reject_existing_listing(workspace, design_name)
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

    saved = ensure_garment_profile(workspace, blueprint, provider, variant_set)
    slug = saved.slug
    typer.echo(f"{'wrote' if saved.written else 'reusing existing'} garment-profiles/{slug}.yaml")

    plan_path = _pick_or_create_pricing_plan(
        workspace,
        catalog,
        GarmentOffer(slug, blueprint, provider, variant_set, saved.profile.sizes),
    )
    plan_ref = make_pricing_plan_ref(plan_path, root=workspace.root)

    colours = listing_colours(saved.profile, colour_slugs)
    media = build_media_entries(template=mockup_template, kind=template_kind, colours=colours)
    _report_media_choice(mockup_template, template_kind, colours, media)
    listing_data = ListingStub(
        garment_profile_slug=slug,
        design_ref=workspace.design_file(design_name).relative_to(workspace.root).as_posix(),
        colours=colours,
        pricing_plan_ref=plan_ref,
        brief="",
        media=media,
    ).document()
    validate_listing_stub(listing_data, currency=workspace.defaults.etsy.currency)
    path = ListingDocuments(workspace).create(design_name, listing_data)
    typer.echo(f"wrote {path}")
