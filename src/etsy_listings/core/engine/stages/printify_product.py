from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import override

from pydantic import BaseModel, ConfigDict

from etsy_listings.core.clients.printify.models import (
    PlacedImage,
    Placeholder,
    PrintAreaSpec,
    Product,
    ProductSpec,
)
from etsy_listings.core.clients.printify.resolve import (
    resolve_blueprint,
    resolve_print_provider,
    resolve_variants,
)
from etsy_listings.core.config.artwork import DesignMap, Tone
from etsy_listings.core.config.garment_profile import GarmentProfile
from etsy_listings.core.config.listing import Listing
from etsy_listings.core.config.money import Money
from etsy_listings.core.engine.change import Verdict
from etsy_listings.core.engine.context import RunContext
from etsy_listings.core.engine.lock import Lockfile, hash_file
from etsy_listings.core.engine.stage import Blocked, Stage, StageApplyResult
from etsy_listings.core.engine.stages.gates import (
    check_artwork,
    check_design_resolution,
    check_garment_profile_chosen,
    check_price_source,
    concrete_description,
    resolved_design,
)
from etsy_listings.core.engine.stages.product_diff import compare
from etsy_listings.core.engine.stages.product_document import (
    AppliedProduct,
    ArtworkGroup,
    PricedVariant,
    PrintifyProductDesired,
    check_garment_unchanged,
    money,
)
from etsy_listings.core.workspace.workspace import Workspace

PRODUCT_ID_KEY = "printify_product_id"
UPLOAD_IDS_KEY = "printify_upload_ids"
"""This stage's key prefix in ``lock.remote``. ``printify_upload_ids``
maps a design's content hash to the upload id Printify gave it -- keyed on
content, not on artwork name, because uploads are content-addressed and a
renamed file is the same upload."""


class ProductVariantSnapshot(BaseModel):
    """One cell of the variant matrix, named rather than left as an id."""

    model_config = ConfigDict(frozen=True)

    size: str
    colour: str
    price: Money


class ProductSnapshot(BaseModel):
    """Domain facts for the before/after review: every variant on each
    side, unchanged ones included -- a ``Plan`` carries only what changed, and
    the comparison needs the whole matrix to draw a price table from."""

    model_config = ConfigDict(frozen=True)

    desired: tuple[ProductVariantSnapshot, ...]
    live: tuple[ProductVariantSnapshot, ...]


NO_SHOP_BLOCKED = Blocked(
    "this listing will not be uploaded to Printify: no Printify "
    "shop is configured for this workspace.\n"
    "Run `etsy-listings setup` to point it at one."
)
"""A workspace no ``setup`` has pointed at a Printify shop, which still renders
mockups: reported as a blocked stage, not an error, and the gates below fire
only once a shop is set."""


@dataclass(frozen=True)
class _ListingInputs:
    config: Listing
    profile: GarmentProfile
    description: str
    paths: dict[str, Path]


def _listing_inputs(workspace: Workspace, listing: str) -> _ListingInputs | Blocked:
    config = workspace.load_listing(listing)
    blocked = check_garment_profile_chosen(config.garment_profile)
    if blocked is not None:
        return blocked
    profile = workspace.load_garment_profile(config.garment_profile)

    # ADR-0043: an unpriced listing is written, and refused here. Before the
    # variants are built, because `resolved_price` raises `KeyError` rather
    # than refusing, and a `KeyError` ends a `--all` batch.
    blocked = check_price_source(pricing_plan=config.pricing_plan, priced_sizes=bool(config.prices))
    if blocked is not None:
        return blocked

    description = concrete_description(config.etsy, workspace.compose_description)
    if isinstance(description, Blocked):
        return description

    blocked = check_artwork(config, profile, {})
    if blocked is not None:
        return blocked
    listing_dir = workspace.listing_dir(listing)
    paths = {
        ref: workspace.resolve_ref(ref, listing_dir=listing_dir)
        for ref in dict.fromkeys(ref for ref in config.design.values() if ref is not None)
    }
    for path in paths.values():
        blocked = check_design_resolution(path, profile)
        if blocked is not None:
            return blocked
    return _ListingInputs(config, profile, description, paths)


class PrintifyProductStage(Stage[PrintifyProductDesired, AppliedProduct, Product]):
    name = "printify_product"
    local = False
    group: str | None = None
    applied_model = AppliedProduct

    @override
    def desired(
        self, ctx: RunContext, listing: str, applied: AppliedProduct | None
    ) -> PrintifyProductDesired | Blocked:
        """The garment check runs before the variant matrix and pricing plan."""
        workspace = ctx.workspace
        if workspace.defaults.printify.shop_id is None:
            return NO_SHOP_BLOCKED

        inputs = _listing_inputs(workspace, listing)
        if isinstance(inputs, Blocked):
            return inputs
        config, profile, paths = inputs.config, inputs.profile, inputs.paths

        resolved = resolve_variant_pricing(ctx, listing)

        blocked = check_garment_unchanged(
            applied,
            blueprint_id=resolved.blueprint_id,
            print_provider_id=resolved.print_provider_id,
        )
        if blocked is not None:
            return blocked

        groups = _group_by_design(
            config.design,
            profile.colors,
            [variant.colour_slug for variant in resolved.variants],
            paths,
        )
        if isinstance(groups, Blocked):
            return groups

        return PrintifyProductDesired(
            title=config.etsy.title,
            description=inputs.description,
            blueprint_id=resolved.blueprint_id,
            print_provider_id=resolved.print_provider_id,
            position=profile.placeholder,
            variants=resolved.variants,
            groups=groups,
            missing=resolved.missing,
            currency=workspace.defaults.etsy.currency,
        )

    @override
    def read_live(
        self, ctx: RunContext, listing: str, lock: Lockfile, applied: AppliedProduct | None
    ) -> Product | None:
        del applied
        product_id = lock.remote.get(PRODUCT_ID_KEY)
        if not product_id:
            return None
        return ctx.require_printify().get_product(_shop_id(ctx), str(product_id))

    @override
    def plan(
        self,
        desired: PrintifyProductDesired,
        applied: AppliedProduct | None,
        live: Product | None,
    ) -> Verdict:
        return compare(desired, applied, live)

    @override
    def snapshot(self, desired: PrintifyProductDesired, live: Product | None) -> ProductSnapshot:
        """Printify's ``ProductVariant`` has no colour or size, so live rows are
        named through this run's resolved ``desired.variants``."""
        lookup = {variant.id: variant for variant in desired.variants}
        desired_rows = tuple(
            _variant_row(variant.colour_slug, variant.size, variant.price, desired.currency)
            for variant in sorted(desired.variants, key=lambda v: (v.colour_slug, v.size))
        )
        live_rows: tuple[ProductVariantSnapshot, ...] = ()
        if live is not None:
            named = sorted(
                (v for v in live.variants if v.is_enabled and v.id in lookup),
                key=lambda v: (lookup[v.id].colour_slug, lookup[v.id].size),
            )
            live_rows = tuple(
                _variant_row(lookup[v.id].colour_slug, lookup[v.id].size, v.price, desired.currency)
                for v in named
            )
        return ProductSnapshot(desired=desired_rows, live=live_rows)

    @override
    def apply(
        self,
        ctx: RunContext,
        desired: PrintifyProductDesired,
        applied: AppliedProduct | None,
        live: Product | None,
        lock: Lockfile,
    ) -> StageApplyResult:
        client = ctx.require_printify()
        shop_id = _shop_id(ctx)

        uploads = dict(lock.remote.get(UPLOAD_IDS_KEY) or {})
        for group in desired.groups:
            if group.design_hash not in uploads:
                ctx.emit(f"uploading {group.design.name}")
                uploads[group.design_hash] = client.upload_image(
                    group.design.name, group.design.read_bytes()
                ).id

        spec = _spec(desired, uploads)

        if live is None:
            adopted = client.find_product_by_copy(
                shop_id, title=desired.title, description=desired.description
            )
            if adopted:
                ctx.emit(f"adopting existing product {adopted}")
                live = client.get_product(shop_id, adopted)

        if live is None:
            ctx.emit(f"creating product ({len(spec.variants)} variants)")
            product = client.create_product(shop_id, spec)
        else:
            ctx.emit(f"updating product {live.id}")
            product = client.update_product(shop_id, live.id, spec, live=live)

        return StageApplyResult(
            applied=desired.applied().model_dump(mode="json"),
            remote={PRODUCT_ID_KEY: product.id, UPLOAD_IDS_KEY: uploads},
        )


def _shop_id(ctx: RunContext) -> int:
    return ctx.workspace.defaults.printify.require_shop_id()


def _variant_row(colour: str, size: str, minor_units: int, currency: str) -> ProductVariantSnapshot:
    return ProductVariantSnapshot(colour=colour, size=size, price=money(minor_units, currency))


@dataclass(frozen=True)
class ResolvedVariantPricing:
    blueprint_id: int
    print_provider_id: int
    variants: tuple[PricedVariant, ...]
    missing: tuple[tuple[str, str], ...]


def resolve_variant_pricing(ctx: RunContext, listing: str) -> ResolvedVariantPricing:
    workspace = ctx.workspace
    config = workspace.load_listing(listing)
    profile = workspace.load_garment_profile(config.garment_profile)

    blueprint = resolve_blueprint(
        profile.blueprint.brand, profile.blueprint.model, ctx.catalog.blueprints()
    )
    provider = resolve_print_provider(
        profile.print_provider, ctx.catalog.print_providers(blueprint.id)
    )

    resolution = resolve_variants(
        ctx.catalog.variants(blueprint.id, provider.id),
        config.colors,
        profile.sizes,
        workspace.load_exceptions(),
    )

    plan_file = config.pricing_plan
    pricing_plan = (
        workspace.load_pricing_plan(
            workspace.resolve_ref(plan_file, listing_dir=workspace.listing_dir(listing))
        )
        if plan_file
        else None
    )
    variants = tuple(
        PricedVariant(
            id=variant.id,
            colour_slug=variant.colour_slug,
            size=variant.size,
            price=config.resolved_price(
                variant.colour_slug, variant.size, pricing_plan=pricing_plan
            ).minor_units,
        )
        for variant in resolution.variants
    )

    return ResolvedVariantPricing(
        blueprint_id=blueprint.id,
        print_provider_id=provider.id,
        variants=variants,
        missing=resolution.missing,
    )


def _group_by_design(
    design: DesignMap,
    tones: Mapping[str, Tone],
    colours: Sequence[str],
    paths: Mapping[str, Path],
) -> tuple[ArtworkGroup, ...] | Blocked:
    digests: dict[str, str] = {}
    groups: dict[str, tuple[Path, list[str]]] = {}
    for colour in dict.fromkeys(colours):
        ref = resolved_design(design, colour, tones, where="the Printify product")
        if isinstance(ref, Blocked):
            return ref
        if ref not in digests:
            digests[ref] = hash_file(paths[ref])
        _, grouped = groups.setdefault(digests[ref], (paths[ref], []))
        grouped.append(colour)
    return tuple(
        ArtworkGroup(design=path, design_hash=digest, colours=tuple(grouped))
        for digest, (path, grouped) in groups.items()
    )


def _spec(desired: PrintifyProductDesired, uploads: dict[str, str]) -> ProductSpec:
    return ProductSpec(
        title=desired.title,
        description=desired.description,
        blueprint_id=desired.blueprint_id,
        print_provider_id=desired.print_provider_id,
        variants=desired.prices,
        print_areas=tuple(
            PrintAreaSpec(
                variant_ids=desired.variant_ids(group),
                placeholders=(
                    Placeholder(
                        position=desired.position,
                        images=(PlacedImage(id=uploads[group.design_hash]),),
                    ),
                ),
            )
            for group in desired.groups
        ),
    )
