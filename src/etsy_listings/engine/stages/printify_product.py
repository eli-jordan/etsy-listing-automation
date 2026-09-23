"""The ``printify_product`` stage: the first one that writes to a remote API.

Built against [docs/api-findings.md](../../../../docs/api-findings.md) rather
than the API reference, because several of the answers are not the obvious
ones and each has produced a plausible-looking wrong implementation:

- The product comes back carrying the **whole blueprint matrix** -- 238
  variants for a product created with 6 -- so every comparison goes through
  the enabled subset.
- ``variants`` on an update **merges by id**. Omitting one does not disable
  it, so a dropped colour has to be retired explicitly, with a price, because
  a variant entry is never partial.
- ``print_areas.variant_ids`` must cover **every** variant on an update and
  only the created ones on create, which is why ``apply`` branches and why an
  update reads the product first.
- ``POST products.json`` has no idempotency key and no conflict, so nothing on
  the server stops a re-run making a second product (PRD 48).

The desired document is deliberately *not* the API's shape. It holds design
**content hashes** where the payload holds upload ids: an upload id is remote
state that only exists after a call, and putting one in a hashed document
would mean `plan` could not run without the network. ``apply`` resolves hash
to upload id, from the lockfile where it can and by uploading where it cannot.

What is left here is what genuinely needs a context: resolving a listing into
a desired product, reading the live one, and sending it. The two documents and
the gate that reads one live in
:mod:`~etsy_listings.engine.stages.product_document`, and the comparison over
them in :mod:`~etsy_listings.engine.stages.product_diff` -- both pure, both
reachable without a workspace. ``plan()`` below assembles a ``Verdict`` from
what the comparison decided; it decides nothing itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from etsy_listings.clients.printify.models import (
    PlacedImage,
    Placeholder,
    PrintAreaSpec,
    Product,
    ProductSpec,
)
from etsy_listings.clients.printify.resolve import (
    resolve_blueprint,
    resolve_print_provider,
    resolve_variants,
)
from etsy_listings.config.money import Money
from etsy_listings.engine.change import Verdict
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.stage import Blocked, StageApplyResult
from etsy_listings.engine.stages.gates import (
    check_copy_is_concrete,
    check_design_resolution,
    check_garment_profile_chosen,
)
from etsy_listings.engine.stages.placement import DesignPlacement
from etsy_listings.engine.stages.product_diff import compare
from etsy_listings.engine.stages.product_document import (
    AppliedProduct,
    PricedVariant,
    PrintifyProductDesired,
    check_garment_unchanged,
    money,
)
from etsy_listings.workspace.common_copy import CommonCopyError

PRODUCT_ID_KEY = "printify_product_id"
UPLOAD_IDS_KEY = "printify_upload_ids"
"""This stage's key prefix in ``lock.remote`` (A20). ``printify_upload_ids``
maps a design's content hash to the upload id Printify gave it -- keyed on
content, not on artwork name, because uploads are content-addressed and a
renamed file is the same upload."""


class ProductVariantSnapshot(BaseModel):
    """One cell of the variant matrix, named rather than left as an id (A30)."""

    model_config = ConfigDict(frozen=True)

    size: str
    colour: str
    price: Money


class ProductSnapshot(BaseModel):
    """Domain facts for the before/after review (A30): every variant on each
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
"""A workspace that has not opted into Phase 2.

Reported as a blocked stage rather than an error, because the alternative is
that adding this stage to the pipeline breaks every Phase 1 workflow: a
listing with no title or description filled in yet is perfectly valid for
rendering mockups, and `plan` refusing to run at all would be a regression
dressed as a validation. The gates below fire only once ``setup`` has pointed
the workspace at a shop -- which is exactly when a product becomes a thing
that could exist.
"""


class PrintifyProductStage:
    name = "printify_product"
    local = False
    applied_model = AppliedProduct

    def desired(
        self, ctx: RunContext, listing: str, applied: AppliedProduct | None
    ) -> PrintifyProductDesired | Blocked:
        """The product this listing wants, or why there cannot be one.

        Every reason this stage cannot run comes back as a
        :class:`~etsy_listings.engine.stage.Blocked` -- the unconfigured
        workspace, the gate refusals and the garment check alike. One
        vocabulary, and now one *place*: the garment check used to refuse from
        ``plan()``, so a stage had two ways to say the same thing and the
        second one arrived with a fully resolved desired document behind it.
        It runs here as soon as the two ids it compares are known -- after the
        blueprint and provider lookups it needs, before the variant matrix and
        the pricing plan it does not.
        """
        workspace = ctx.workspace
        if workspace.defaults.printify.shop_id is None:
            return NO_SHOP_BLOCKED

        config = workspace.load_listing(listing)
        blocked = check_garment_profile_chosen(config.garment_profile)
        if blocked is not None:
            return blocked
        profile = workspace.load_garment_profile(config.garment_profile)

        blocked = check_copy_is_concrete(title=config.etsy.title, lead=config.etsy.description.lead)
        if blocked is not None:
            return blocked
        try:
            description = workspace.compose_description(config.etsy.description)
        except CommonCopyError as exc:
            return Blocked(str(exc))

        placement = DesignPlacement.resolve(workspace, listing, config, profile)
        for path in placement.paths.values():
            blocked = check_design_resolution(path, profile)
            if blocked is not None:
                return blocked

        resolved = resolve_variant_pricing(ctx, listing)

        blocked = check_garment_unchanged(
            applied,
            blueprint_id=resolved.blueprint_id,
            print_provider_id=resolved.print_provider_id,
        )
        if blocked is not None:
            return blocked

        return PrintifyProductDesired(
            title=config.etsy.title,
            description=description,
            blueprint_id=resolved.blueprint_id,
            print_provider_id=resolved.print_provider_id,
            position=profile.placeholder,
            variants=resolved.variants,
            groups=placement.group_by_artwork([v.colour_slug for v in resolved.variants]),
            missing=resolved.missing,
            currency=workspace.defaults.etsy.currency,
        )

    def read_live(
        self, ctx: RunContext, listing: str, lock: Lockfile, applied: AppliedProduct | None
    ) -> Product | None:
        """The product, or ``None``.

        ``None`` **without a request** when the lockfile has no product id:
        there is nothing to read before the first apply, and asking would make
        every `plan` in a fresh workspace demand a token for a command that
        changes nothing.
        """
        del applied
        product_id = lock.remote.get(PRODUCT_ID_KEY)
        if not product_id:
            return None
        return ctx.require_printify().get_product(_shop_id(ctx), str(product_id))

    def plan(
        self,
        desired: PrintifyProductDesired,
        applied: AppliedProduct | None,
        live: Product | None,
    ) -> Verdict:
        """Three states in, a verdict out. Everything else moved."""
        comparison = compare(desired, applied, live)
        if comparison.reason is None:
            return Verdict.no_work(drift=comparison.drift)
        return Verdict.work(
            comparison.reason,
            changes=comparison.changes,
            drift=comparison.drift,
            actions=comparison.actions,
        )

    def snapshot(self, desired: PrintifyProductDesired, live: Product | None) -> ProductSnapshot:
        """Every variant, both sides, named (A30).

        The id -> (colour, size) lookup a live variant needs is
        ``desired.variants``, this run's own resolved matrix -- the same one
        ``apply`` sends -- since :class:`~etsy_listings.clients.printify.models.ProductVariant`
        carries no colour or size of its own. A live variant whose id has
        fallen out of that resolution (a garment change would have already
        been blocked; a discontinued cell, PRD 46) has nothing to be named by
        and is left off the live side rather than guessed at.
        """
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

    def apply(
        self,
        ctx: RunContext,
        desired: PrintifyProductDesired,
        applied: AppliedProduct | None,
        live: Product | None,
        lock: Lockfile,
    ) -> StageApplyResult:
        """``live`` is the product ``read_live`` already fetched during
        planning, not a second ``GET`` for the same id.

        ``desired`` is a document, never a refusal: a blocked stage is never
        flagged to run, so the ``isinstance`` branch that used to open this
        method -- unreachable, and marked ``no cover`` to say so -- is gone
        along with the union it was testing.
        """
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
            # PRD 48: the lockfile is the primary guard, and this walk closes
            # the one window it cannot -- create succeeded, the process died
            # before the lockfile was written. Only on the create path, so a
            # no-op run never pays for it.
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


# ------------------------------------------------------------------ helpers


def _shop_id(ctx: RunContext) -> int:
    return ctx.workspace.defaults.printify.require_shop_id()


def _variant_row(colour: str, size: str, minor_units: int, currency: str) -> ProductVariantSnapshot:
    return ProductVariantSnapshot(colour=colour, size=size, price=money(minor_units, currency))


@dataclass(frozen=True)
class ResolvedVariantPricing:
    """The blueprint, print provider and priced variant matrix a listing
    resolves to -- everything about a Printify product that depends on the
    catalog and nothing about its artwork or copy."""

    blueprint_id: int
    print_provider_id: int
    variants: tuple[PricedVariant, ...]
    missing: tuple[tuple[str, str], ...]


def resolve_variant_pricing(ctx: RunContext, listing: str) -> ResolvedVariantPricing:
    """Resolve a listing's garment and priced variant matrix from the catalog.

    Shared with the `publish` stage (phase-3-etsy.md decision 1), which
    rebuilds its own desired variant matrix through this same function rather
    than reading this stage's lockfile subtree -- the cost is one extra
    resolution pass per listing per run (the catalog is disk-cached; the rest
    is arithmetic), and it buys the two stages independence from each other's
    lockfile shape.
    """
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
            workspace.resolve(plan_file, relative_to=workspace.listing_dir(listing))
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
