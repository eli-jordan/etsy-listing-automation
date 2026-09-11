"""What Printify's endpoints return, on both sides of the client.

Two families in one module, because they are one API's vocabulary and a stage
routinely holds both: the product stage resolves a :class:`Variant` id out of
the catalog and puts it in a :class:`ProductSpec` in the same breath.

*Reference data* -- :class:`Blueprint`, :class:`PrintProvider`,
:class:`Variant`, :class:`ShippingRates` -- is the read-only, shop-agnostic
half (PRD 7b). Read-only, but not unauthenticated: every catalog call needs a
token with the ``catalog.read`` scope, same as the rest of the API.

*Shop-scoped state* -- :class:`Shop`, :class:`Upload`, :class:`Product`,
:class:`ProductSpec` -- is what a shop owns and this tool writes.

Every model is deliberately lenient about extra keys and strict about the ones
it names: Printify adds fields without warning, and a client that treats a new
one as a validation error breaks on a day nobody deployed anything.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

# --------------------------------------------------------------- reference data


class Blueprint(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    title: str
    brand: str
    model: str


class PrintProvider(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    title: str


class VariantOptions(BaseModel):
    model_config = ConfigDict(frozen=True)

    color: str
    size: str


class PrintAreaPlaceholder(BaseModel):
    model_config = ConfigDict(frozen=True)

    position: str
    width: int
    height: int

    @property
    def area(self) -> int:
        return self.width * self.height


class Variant(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    title: str
    options: VariantOptions
    placeholders: tuple[PrintAreaPlaceholder, ...] = ()
    """**Per variant, which is where Printify actually puts them.** The
    variants endpoint has no top-level ``placeholders`` key; each variant
    carries its own list. Reading the response as though it did is how every
    profile came out with no ``front`` placeholder and ``new`` died on
    "Available: (none)".

    They are per-variant because they genuinely differ: on Comfort Colors
    1717 / Monster Digital, ``front`` is 3461x3955 on the small sizes and
    4200x4800 on the large ones."""


class VariantSet(BaseModel):
    model_config = ConfigDict(frozen=True)

    variants: tuple[Variant, ...]

    @property
    def colors(self) -> list[str]:
        seen: dict[str, None] = {}
        for variant in self.variants:
            seen.setdefault(variant.options.color, None)
        return list(seen)

    def positions(self) -> list[str]:
        """Every print position this combination offers, first seen first."""
        seen: dict[str, None] = {}
        for variant in self.variants:
            for placeholder in variant.placeholders:
                seen.setdefault(placeholder.position, None)
        return list(seen)

    def placeholder_sizes(self, position: str) -> list[PrintAreaPlaceholder]:
        """Every distinct size offered at ``position``, largest first.

        Distinct by dimensions rather than by variant: a 229-variant set
        typically offers two or three sizes across all of them, and the same
        size repeated under several decoration methods.
        """
        distinct = {
            (p.width, p.height): p
            for variant in self.variants
            for p in variant.placeholders
            if p.position == position
        }
        return sorted(distinct.values(), key=lambda p: (p.area, p.width, p.height), reverse=True)

    def placeholder(self, position: str) -> PrintAreaPlaceholder | None:
        """The **largest** size offered at ``position``, or ``None``.

        A profile carries one print area (PRD 8a) and the catalog offers
        several, so one has to win. The largest does, because the print area
        is a resolution target -- a design must come within 10% of it in each
        axis (PRD 38) -- and art sized for the 3XL panel still covers the S
        panel, while the reverse prints soft on the sizes that need it most.
        """
        sizes = self.placeholder_sizes(position)
        return sizes[0] if sizes else None


class ShippingCost(BaseModel):
    model_config = ConfigDict(frozen=True)

    currency: str
    cost: int
    """Cents, as Printify sends it -- not a ``Money`` (that type wants a
    workspace-currency-checked amount; this is a raw USD catalog figure a
    caller converts, it doesn't validate against ``shop.yaml`` itself)."""


class ShippingProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    variant_ids: tuple[int, ...]
    first_item: ShippingCost
    additional_items: ShippingCost


class ShippingRates(BaseModel):
    model_config = ConfigDict(frozen=True)

    profiles: tuple[ShippingProfile, ...]

    def first_item_cost_cents(self, variant_id: int) -> int | None:
        for profile in self.profiles:
            if variant_id in profile.variant_ids:
                return profile.first_item.cost
        return None


# ------------------------------------------------------------ shop-scoped state


class Shop(BaseModel):
    """One row of ``GET /v1/shops.json`` -- which is the whole of what that
    endpoint knows. No currency, no settings, no draft preference
    (docs/api-findings.md).

    The call is scoped to the token, so its answer is also the answer to "which
    shops may this token write to?" -- which is what makes ``setup`` able to
    discover the shop id rather than asking a human to find one (PRD 42).
    """

    model_config = ConfigDict(frozen=True)

    id: int
    title: str
    sales_channel: str | None = None
    """``"etsy"`` once a shop is connected, ``"disconnected"`` before that.
    Optional because Printify omits keys rather than nulling them, and nothing
    here may assume a field is present."""

    @property
    def is_connected(self) -> bool:
        """Whether a publish could reach a sales channel at all.

        ``publish.json`` against a disconnected shop is
        ``400 code 8254``, so this is the difference between "Phase 3 will
        work here" and "Phase 3 cannot be tested here".
        """
        return self.sales_channel not in (None, "", "disconnected")


class Upload(BaseModel):
    """What ``POST /v1/uploads/images.json`` gives back.

    Uploads are **content-addressed**: the same bytes return the same ``id``
    and the same ``upload_time``, and ``file_name`` takes no part in it. So
    re-uploading is safe -- merely wasteful, since it still ships the
    megabytes -- which is why the id is cached in the lockfile against the
    design's content hash rather than guarded by anything cleverer.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    file_name: str = ""
    width: int = 0
    height: int = 0


class PlacedImage(BaseModel):
    """A design placed in a print area, projected to the five fields we set.

    We send five; the product returns fourteen -- ``name``, ``type``,
    ``width``, ``height``, ``flipX``, ``flipY``, ``src``, ``layerType`` and an
    ``imageId`` distinct from the upload id. Comparing all of them against a
    desired document is a permanent spurious diff, so the extras are dropped
    on the way in rather than filtered at every comparison
    (docs/api-findings.md).

    The defaults are PRD 45's fixed placement: centred, fit inside the print
    area, unrotated. There is no configuration surface for them in v1 --
    PRD 38's >=90% gate is what makes the constant right rather than arbitrary.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    x: float = 0.5
    y: float = 0.5
    scale: float = 1.0
    angle: float = 0


class Placeholder(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    position: str
    images: tuple[PlacedImage, ...] = ()


class PrintAreaSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    variant_ids: tuple[int, ...]
    placeholders: tuple[Placeholder, ...]


class ProductVariant(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: int
    price: int
    is_enabled: bool = False
    cost: int = 0
    """Printify's per-variant manufacturing cost, in minor units of USD. Read
    only, and not part of any comparison -- it is Printify's fact, not our
    desired state. The publish stage asserts the retail price clears it
    (PRD 40, amended), which is the one place it matters."""
    is_available: bool = True


class ProductExternal(BaseModel):
    """A published product's link to the sales channel, narrowed to what
    Phase 3 reads. ``type`` (observed ``4``, undocumented) is dropped
    deliberately -- recording it only so the next reader does not think it
    means something."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    handle: str | None = None
    shipping_template_id: str | None = None


class Product(BaseModel):
    """A product as Printify holds it, projected to what we can actually set.

    ``variants`` arrives as the **whole blueprint matrix** -- 238 entries for a
    product created with 6 -- so every comparison goes through
    :meth:`enabled_variants`. The full list is kept because an update has to
    name every variant in ``print_areas.variant_ids`` (the coverage rule), and
    that is the only place it is needed.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    title: str = ""
    description: str = ""
    blueprint_id: int = 0
    print_provider_id: int = 0
    variants: tuple[ProductVariant, ...] = ()
    print_areas: tuple[PrintAreaSpec, ...] = ()
    visible: bool = True
    """Kept as a tripwire. A product this tool manages coming back visible
    means something outside it changed the one setting that decides whether a
    publish is reviewable."""
    is_locked: bool = False
    is_deleted: bool = False
    external: ProductExternal | None = None
    """Absent from the response until a publish succeeds -- decoded as
    optional-*missing*, not optional-null, because that is how Printify sends
    it."""

    @model_validator(mode="after")
    def _drop_empty_placeholders(self) -> Product:
        """`back` comes back with `images: []` on a product that only uses
        `front`. A placeholder we never placed anything in is not a
        difference, and carrying it makes every comparison report one."""
        pruned = tuple(
            area.model_copy(
                update={"placeholders": tuple(p for p in area.placeholders if p.images)}
            )
            for area in self.print_areas
        )
        if pruned != self.print_areas:
            object.__setattr__(self, "print_areas", pruned)
        return self

    def enabled_variants(self) -> dict[int, int]:
        """``{variant_id: price}`` for the enabled subset -- the product's real
        content, and the only part a desired document describes."""
        return {v.id: v.price for v in self.variants if v.is_enabled}

    def all_variant_ids(self) -> tuple[int, ...]:
        """Every variant the product carries, for the update coverage rule."""
        return tuple(v.id for v in self.variants)


class ProductSpec(BaseModel):
    """What we want a product to be. Not what Printify returns -- see
    :class:`Product` for the difference and why it matters."""

    model_config = ConfigDict(frozen=True)

    title: str
    description: str
    blueprint_id: int
    print_provider_id: int
    variants: dict[int, int]
    """``{variant_id: price}``, in minor units of the sales channel's currency
    (PRD 39/40 -- NOK passes through unconverted). The enabled set; anything
    absent is either untouched, on create, or explicitly disabled, on update."""
    print_areas: tuple[PrintAreaSpec, ...]
