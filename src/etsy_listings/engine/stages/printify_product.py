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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from etsy_listings.catalog.resolve import (
    VariantResolution,
    resolve_blueprint,
    resolve_print_provider,
    resolve_variants,
)
from etsy_listings.clients.printify.models import (
    PlacedImage,
    Placeholder,
    PrintAreaSpec,
    Product,
    ProductSpec,
)
from etsy_listings.clients.printify.protocol import PrintifyClient
from etsy_listings.config.money import Money
from etsy_listings.engine.change import (
    Action,
    Change,
    Drift,
    FieldChange,
    PriceChange,
    StagePlan,
    drift,
    scalar,
)
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.stage import Blocked, StageApplyResult, StageBlockedError
from etsy_listings.engine.stages.gates import (
    check_copy_is_concrete,
    check_design_resolution,
    check_garment_unchanged,
)
from etsy_listings.engine.stages.placement import ArtworkGroup, DesignPlacement

PRODUCT_ID_KEY = "printify_product_id"
UPLOAD_IDS_KEY = "printify_upload_ids"
"""This stage's key prefix in ``lock.remote`` (A20). ``printify_upload_ids``
maps a design's content hash to the upload id Printify gave it -- keyed on
content, not on artwork name, because uploads are content-addressed and a
renamed file is the same upload."""


NO_SHOP_BLOCKED = Blocked(
    "this listing will not be uploaded to Printify: no Printify "
    "shop is configured for this workspace.\n"
    "Run `etsy-listings setup` to point it at one."
)
"""A workspace that has not opted into Phase 2.

Reported as a blocked stage rather than an error, because the alternative is
that adding this stage to the pipeline breaks every Phase 1 workflow: a
listing whose copy is still ``<generate>`` is perfectly valid for rendering
mockups, and `plan` refusing to run at all would be a regression dressed as a
validation. The gates below fire only once ``setup`` has pointed the workspace
at a shop -- which is exactly when a product becomes a thing that could exist.
"""


class MissingPrintifyClientError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "this run has no Printify client, so the product stage cannot run. "
            "That is a wiring bug, not a configuration problem."
        )


@dataclass(frozen=True)
class PrintifyProductDesired:
    title: str
    description: str
    blueprint_id: int
    print_provider_id: int
    position: str
    prices: dict[int, int]
    groups: tuple[ArtworkGroup, ...]
    resolution: VariantResolution
    currency: str = ""
    price_labels: dict[int, tuple[str, str]] = field(default_factory=dict)
    """``variant_id -> (colour_slug, size)``, so a ``PriceChange`` can name the
    cell a human recognises instead of an integer they have never seen."""

    def variant_ids(self, group: ArtworkGroup) -> tuple[int, ...]:
        """The Printify variants a group's colours resolve to.

        The group itself knows only colours -- which ink a colour gets is a
        fact about the listing, not about Printify -- so turning them into ids
        is this stage's half of the job, and it is the one place that does it.
        """
        return self.resolution.ids(colours=set(group.colours))

    def document(self) -> dict[str, Any]:
        """The hashable ``applied`` form: no paths, no upload ids, no clock.

        Variants are a sorted list of objects rather than a dict keyed by id,
        because a JSON round-trip turns integer keys into strings and the
        comparison would then find a difference on every run.
        """
        return {
            "title": self.title,
            "description": self.description,
            "blueprint_id": self.blueprint_id,
            "print_provider_id": self.print_provider_id,
            "position": self.position,
            "variants": [
                {"id": variant_id, "price": self.prices[variant_id]}
                for variant_id in sorted(self.prices)
            ],
            "print_areas": [
                {
                    "artwork": group.artwork,
                    "design_hash": group.design_hash,
                    "variant_ids": list(self.variant_ids(group)),
                }
                for group in self.groups
            ],
        }


def _money(minor_units: int, currency: str) -> Money:
    """Minor units back into the form the config was written in."""
    return Money(Decimal(minor_units) / 100, currency)


class PrintifyProductStage:
    name = "printify_product"
    local = False

    def desired(self, ctx: RunContext, listing: str) -> PrintifyProductDesired | Blocked:
        """The product this listing wants, or why there cannot be one.

        Every reason this stage cannot run comes back as a
        :class:`~etsy_listings.engine.stage.Blocked` -- the unconfigured
        workspace and the gate refusals alike. One vocabulary: `plan` reports
        all of them the same way, and none of them can unwind the stage walk
        and take the render stage's plan down with it.
        """
        workspace = ctx.workspace
        if workspace.defaults.printify.shop_id is None:
            return NO_SHOP_BLOCKED

        config = workspace.load_listing(listing)
        profile = workspace.load_profile(config.profile)

        # The gates that do not need the lockfile run here, so `plan` refuses
        # before it has built a payload nobody wants sent. The garment check
        # needs `applied` and runs in `plan()`.
        blocked = check_copy_is_concrete(
            title=config.etsy.title, description=config.etsy.description
        )
        if blocked is not None:
            return blocked

        placement = DesignPlacement.resolve(workspace, listing, config, profile)
        for path in placement.paths.values():
            blocked = check_design_resolution(path, profile)
            if blocked is not None:
                return blocked

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
        prices = {
            variant.id: config.resolved_price(
                variant.colour_slug, variant.size, pricing_plan=pricing_plan
            ).minor_units
            for variant in resolution.variants
        }

        return PrintifyProductDesired(
            title=config.etsy.title,
            description=config.etsy.description,
            blueprint_id=blueprint.id,
            print_provider_id=provider.id,
            position=profile.placeholder,
            prices=prices,
            groups=placement.group_by_artwork([v.colour_slug for v in resolution.variants]),
            resolution=resolution,
            currency=workspace.defaults.currency,
            price_labels={v.id: (v.colour_slug, v.size) for v in resolution.variants},
        )

    def read_live(self, ctx: RunContext, listing: str, lock: Lockfile) -> Product | None:
        """The product, or ``None``.

        ``None`` **without a request** when the lockfile has no product id:
        there is nothing to read before the first apply, and asking would make
        every `plan` in a fresh workspace demand a token for a command that
        changes nothing.
        """
        product_id = lock.remote.get(PRODUCT_ID_KEY)
        if not product_id:
            return None
        return _client(ctx).get_product(_shop_id(ctx), str(product_id))

    def plan(
        self,
        desired: PrintifyProductDesired | Blocked,
        applied: dict[str, Any] | None,
        live: Product | None,
    ) -> StagePlan:
        if isinstance(desired, Blocked):
            return StagePlan(stage=self.name, will_run=False, blocked=desired.message)

        blocked = check_garment_unchanged(
            applied,
            blueprint_id=desired.blueprint_id,
            print_provider_id=desired.print_provider_id,
        )
        if blocked is not None:
            return StagePlan(stage=self.name, will_run=False, blocked=blocked.message)

        document = desired.document()
        changes = _changes(desired, document, applied)
        will_run = applied is None or bool(changes) or live is None

        return StagePlan(
            stage=self.name,
            will_run=will_run,
            changes=changes,
            drift=_drift(document, live),
            reason=_reason(applied, live, changes),
            actions=_actions(desired, applied is None or live is None),
        )

    def apply(
        self,
        ctx: RunContext,
        stage_plan: StagePlan,
        desired: PrintifyProductDesired | Blocked,
        live: Product | None,
        lock: Lockfile,
    ) -> StageApplyResult:
        """``live`` is the product ``read_live`` already fetched during
        planning, not a second ``GET`` for the same id."""
        if isinstance(desired, Blocked):  # pragma: no cover - `plan` never schedules it
            raise StageBlockedError(desired.message)
        client = _client(ctx)
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
            applied=desired.document(),
            remote={PRODUCT_ID_KEY: product.id, UPLOAD_IDS_KEY: uploads},
        )


# ------------------------------------------------------------------ helpers


def _client(ctx: RunContext) -> PrintifyClient:
    if ctx.printify is None:
        raise MissingPrintifyClientError
    return ctx.printify


def _shop_id(ctx: RunContext) -> int:
    return ctx.workspace.defaults.printify.require_shop_id()


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


def _changes(
    desired: PrintifyProductDesired, document: dict[str, Any], applied: dict[str, Any] | None
) -> tuple[Change, ...]:
    if applied is None:
        return ()

    changes: list[Change] = []
    for path in ("title", "description", "position"):
        change = scalar(path, document[path], applied.get(path))
        if change is not None:
            changes.append(change)

    was_prices = {entry["id"]: entry["price"] for entry in applied.get("variants", [])}
    for variant_id, price in sorted(desired.prices.items()):
        if was_prices.get(variant_id) != price and variant_id in was_prices:
            colour, size = desired.price_labels.get(variant_id, ("?", "?"))
            # Rendered back into `Money` rather than shown as the minor units
            # the document stores. "34900 -> 39900" is the wire format; the
            # user wrote "349 NOK", and that is what a diff has to say back.
            changes.append(
                PriceChange(
                    size=size,
                    color=colour,
                    before=_money(was_prices[variant_id], desired.currency),
                    after=_money(price, desired.currency),
                )
            )

    added = sorted(set(desired.prices) - set(was_prices))
    removed = sorted(set(was_prices) - set(desired.prices))
    if added or removed:
        changes.append(
            FieldChange(path="variants", before=len(was_prices), after=len(desired.prices))
        )

    for index, area in enumerate(document["print_areas"]):
        was = applied.get("print_areas", [])
        previous = was[index] if index < len(was) else None
        if previous != area:
            changes.append(
                FieldChange(
                    path=f"print_areas[{index}].{area['artwork']}",
                    before=(previous or {}).get("design_hash"),
                    after=area["design_hash"],
                )
            )
    return tuple(changes)


def _drift(document: dict[str, Any], live: Product | None) -> tuple[Drift, ...]:
    """What changed in Printify since we last applied.

    Compared against *desired* rather than *applied* only where the two agree
    in shape. The variant matrix is the enabled subset, never the raw list --
    comparing 238 against 6 is a diff that never clears.
    """
    if live is None:
        return ()

    found: list[Drift] = []
    for path, ours, theirs in (
        ("title", document["title"], live.title),
        ("description", document["description"], live.description),
    ):
        change = drift(path, ours, theirs)
        if change is not None:
            found.append(change)

    ours_prices = {entry["id"]: entry["price"] for entry in document["variants"]}
    if live.enabled_variants() != ours_prices:
        found.append(
            Drift(
                path="variants",
                last_applied=f"{len(ours_prices)} enabled",
                live=f"{len(live.enabled_variants())} enabled",
            )
        )

    if live.visible:
        # The tripwire. Whether a publish lands as a draft is decided outside
        # this tool, so a managed product turning visible is the only signal
        # that something changed the setting that decides it.
        found.append(Drift(path="visible", last_applied=False, live=True))
    return tuple(found)


def _reason(
    applied: dict[str, Any] | None, live: Product | None, changes: tuple[Change, ...]
) -> str | None:
    if applied is None:
        return "no Printify product yet -- it will be created"
    if live is None:
        return "the Printify product this listing named is gone -- it will be created again"
    if changes:
        return "the product differs from the listing"
    return None


def _actions(desired: PrintifyProductDesired, creating: bool) -> tuple[Action, ...]:
    verb = "create" if creating else "update"
    described = (
        f"{verb} a Printify product: {len(desired.prices)} variants across "
        f"{len(desired.groups)} print area(s)"
    )
    actions = [
        Action(
            description=described,
            inputs=tuple(sorted(group.design.name for group in desired.groups)),
        )
    ]
    if desired.resolution.missing:
        # PRD 46: reported, never fatal. A cell Printify has discontinued is
        # its fact, not the user's mistake -- but a listing quietly selling
        # five sizes where it asked for six is worth saying out loud.
        listed = ", ".join(f"{colour}/{size}" for colour, size in desired.resolution.missing)
        actions.append(
            Action(
                description=(
                    f"skip {len(desired.resolution.missing)} colour/size "
                    f"combination(s) this garment no longer offers: {listed}"
                )
            )
        )
    return tuple(actions)
