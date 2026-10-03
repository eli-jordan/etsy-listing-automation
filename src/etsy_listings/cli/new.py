"""The ``new`` wizard: a design, garment, provider, template and pricing
plan picked in turn, and a listing stub written from the answers.

Thin by design. This module only sequences the questions and says what
happened; *how* a question gets asked is :mod:`etsy_listings.cli.prompts`,
which picks a backend that can actually drive the terminal it was given
(questionary cannot, under cygwin), and the rows each picker offers are
:mod:`etsy_listings.cli.pickers`'. Every decision and write is core's --
:mod:`~etsy_listings.core.application.garment_profiles`,
:mod:`~etsy_listings.core.application.pricing_plans` and
:mod:`~etsy_listings.core.application.listing_creation` -- which the
behaviour tests also drive through a fake catalog without prompting.

:func:`run_new` is the interface.
"""

from __future__ import annotations

from pathlib import Path

import typer

from etsy_listings.cli import prompts, terminal
from etsy_listings.cli.pickers import (
    CREATE_NEW_PLAN_LABEL,
    LOCAL_MARKER,
    LOCAL_MARKER_FALLBACK,
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
    build_listing_stub,
    build_media_entries,
    load_template_kind,
    validate_listing_stub,
)
from etsy_listings.core.application.pricing_plans import (
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


def _pick_blueprint(workspace: Workspace, blueprints: list[Blueprint]) -> Blueprint:
    """Pick from ``marker brand model title`` rows.

    Even ``--category tshirt`` leaves dozens of blueprints, and Printify's
    titles bury the useful word in the middle ("Unisex Garment-Dyed Heavy
    Weight Tee"), so a scrolling list is the wrong instrument. Garments this
    workspace already has a garment profile for sort to the top and carry a marker: a
    shop reuses a handful of blueprints, and re-finding the one used yesterday
    is this picker's most common job.
    """
    marker = terminal.choose(LOCAL_MARKER, LOCAL_MARKER_FALLBACK)
    choices = build_blueprint_choices(blueprints, local_blueprint_keys(workspace), marker=marker)
    return prompts.pick(
        "Garment",
        choices,
        label=lambda choice: choice.label,
        marker_hint=f"{marker.strip()} = already used in this workspace",
    ).value


def _pick_provider(workspace: Workspace, providers: list[PrintProvider]) -> PrintProvider:
    """The shop's ``preferred_print_provider`` sorts first when it is offered,
    so the common case is the first row rather than a default the fuzzy
    backends have no way to express."""
    preferred = workspace.defaults.printify.preferred_print_provider
    ordered = sorted(providers, key=lambda p: (p.title != preferred, p.title.lower()))
    return prompts.pick("Print provider", ordered, label=lambda provider: provider.title)


def _report_print_area_choice(variant_set: VariantSet) -> None:
    """Say so when the garment profile's print area is one of several on offer.

    Printify's print areas are per-variant and genuinely differ by garment
    size. The garment profile carries exactly one, so `new` records the
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


def _pick_design(workspace: Workspace) -> str:
    """Pick the design from what is in ``designs/``, newest first.

    ``new`` is a wizard, and the design was the one answer it still demanded
    up front on the command line -- which meant knowing the exact stem of a
    file you had just exported. Everything the picker needs is on disk, so it
    asks like it asks everything else. The argument still works, for scripting
    and for naming artwork that does not exist yet.
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
    """Pick from the templates that exist, rather than typing a name.

    A typo used to be accepted silently and produce a listing that failed
    much later at render time, with nothing pointing back at `new`. Reading
    the template is not optional anyway -- its kind decides the shape of a
    valid `media` entry -- so it may as well be picked from the list.
    """
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
    """Say what got a photo and what did not.

    Both branches are surprising in silence: a `single`/`multiple` template
    renders one image no matter how many colours sell, and a `colour-matrix`
    one has to stop at Etsy's 20-image limit while the listing still sells
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
            f"{len(colours)} colours offered, but Etsy allows {MAX_IMAGES} images: "
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
    near = [p.name for p in workspace.design_files() if p.name.startswith(design_name)]
    hint = f" Did you mean {near[0]!r}?" if near else ""
    typer.echo(f"note: {path} does not exist yet.{hint}")


def _pick_or_create_pricing_plan(
    workspace: Workspace,
    catalog: CatalogClient,
    garment_profile_slug: str,
    blueprint: Blueprint,
    provider: PrintProvider,
    variant_set: VariantSet,
    sizes: list[str],
) -> Path:
    """Returns the chosen/generated plan's absolute path -- turning that into
    a ref is the caller's job (`pricing_plan_ref`, ADR-0046)."""
    candidates = load_candidate_pricing_plans(workspace)
    choices = build_pricing_plan_choices(candidates, garment_profile_slug)
    rows = [c.label for c in choices] + [CREATE_NEW_PLAN_LABEL]
    by_label = {c.label: c for c in choices}

    marker = terminal.choose(LOCAL_MARKER, LOCAL_MARKER_FALLBACK)
    # `ask_choice` rather than `pick`: one of the rows is a sentinel that is
    # not a plan at all, so there is no option to map it back to.
    answer = prompts.ask_choice(
        "Pricing plan", rows, marker_hint=f"{marker.strip()} = sizes match this garment exactly"
    )

    if answer == CREATE_NEW_PLAN_LABEL:
        name = prompts.ask_text("Pricing plan name:")
        created = create_starting_pricing_plan(
            workspace,
            catalog,
            name=name,
            garment_profile_slug=garment_profile_slug,
            blueprint=blueprint,
            provider=provider,
            variant_set=variant_set,
            sizes=sizes,
        )
        typer.echo(f"wrote {created.path}")
        if not created.complete:
            typer.echo(
                "  note: some prices could not be computed from live Printify/FX data "
                "-- see the comment at the top of the file for what fell back to 0."
            )
        return created.path

    return by_label[answer].value


def _reject_existing_listing(workspace: Workspace, design_name: str) -> None:
    """Creating the listing refuses a taken name, but it is the *last* thing
    ``new`` does, so without this check the whole wizard would run before
    saying no. It is checked here rather than only on the picked row,
    because a name given as the argument reaches the same dead end."""
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
        workspace, catalog, slug, blueprint, provider, variant_set, saved.profile.sizes
    )
    plan_ref = make_pricing_plan_ref(plan_path, root=workspace.root)

    colours = listing_colours(saved.profile, colour_slugs)
    media = build_media_entries(template=mockup_template, kind=template_kind, colours=colours)
    _report_media_choice(mockup_template, template_kind, colours, media)
    listing_data = build_listing_stub(
        garment_profile_slug=slug,
        design_ref=workspace.design_file(design_name).relative_to(workspace.root).as_posix(),
        colours=colours,
        pricing_plan_ref=plan_ref,
        brief="",
        media=media,
    )
    validate_listing_stub(listing_data, currency=workspace.defaults.etsy.currency)
    path = ListingDocuments(workspace).create(design_name, listing_data)
    typer.echo(f"wrote {path}")
