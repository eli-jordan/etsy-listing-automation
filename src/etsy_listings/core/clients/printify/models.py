"""What Printify's catalog and shop endpoints return and accept.

Every model ignores keys it does not name: Printify adds fields without warning.
"""

from __future__ import annotations

from typing import NewType

from pydantic import BaseModel, ConfigDict, model_validator

UsdCents = NewType("UsdCents", int)


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
    """Per variant, where Printify puts them: the variants endpoint has no top-level
    ``placeholders`` key. They differ by size: on Comfort Colors 1717 / Monster Digital,
    ``front`` is 3461x3955 on the small sizes and 4200x4800 on the large ones."""


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
        seen: dict[str, None] = {}
        for variant in self.variants:
            for placeholder in variant.placeholders:
                seen.setdefault(placeholder.position, None)
        return list(seen)

    def placeholder_sizes(self, position: str) -> list[PrintAreaPlaceholder]:
        """Every distinct size (by dimensions) offered at ``position``, largest first."""
        distinct = {
            (p.width, p.height): p
            for variant in self.variants
            for p in variant.placeholders
            if p.position == position
        }
        return sorted(distinct.values(), key=lambda p: (p.area, p.width, p.height), reverse=True)

    def placeholder(self, position: str) -> PrintAreaPlaceholder | None:
        """The largest size offered at ``position`` (ADR-0018), or ``None``."""
        sizes = self.placeholder_sizes(position)
        return sizes[0] if sizes else None


class ShippingCost(BaseModel):
    model_config = ConfigDict(frozen=True)

    currency: str
    cost: UsdCents
    """A raw catalog figure, not a workspace-currency ``Money``."""


class ShippingProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    variant_ids: tuple[int, ...]
    first_item: ShippingCost
    additional_items: ShippingCost


class ShippingRates(BaseModel):
    model_config = ConfigDict(frozen=True)

    profiles: tuple[ShippingProfile, ...]

    def first_item_cost_cents(self, variant_id: int) -> UsdCents | None:
        for profile in self.profiles:
            if variant_id in profile.variant_ids:
                return profile.first_item.cost
        return None


class Shop(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    title: str
    sales_channel: str | None = None
    """``"etsy"`` once a shop is connected, ``"disconnected"`` before that.
    Optional because Printify omits keys rather than nulling them, and nothing
    here may assume a field is present."""

    @property
    def is_connected(self) -> bool:
        return self.sales_channel not in (None, "", "disconnected")


class Upload(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    file_name: str = ""
    width: int = 0
    height: int = 0


class PlacedImage(BaseModel):
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
    cost: UsdCents = UsdCents(0)
    """Printify's manufacturing cost; read only, never compared. The publish stage checks the retail
    price clears it (ADR-0020)."""
    is_available: bool = True


class ProductExternal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    handle: str | None = None
    shipping_template_id: str | None = None


class Product(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    title: str = ""
    description: str = ""
    blueprint_id: int = 0
    print_provider_id: int = 0
    variants: tuple[ProductVariant, ...] = ()
    print_areas: tuple[PrintAreaSpec, ...] = ()
    visible: bool = True
    """Printify copies this onto the Etsy listing at publish: created
    ``false`` so a first publish lands as a draft, then set by the `publish`
    stage to match the listing's Etsy state before every republish."""
    is_locked: bool = False
    is_deleted: bool = False
    external: ProductExternal | None = None
    """Absent until a publish succeeds: Printify omits the key rather than sending null."""

    @model_validator(mode="after")
    def _drop_empty_placeholders(self) -> Product:
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
        return {v.id: v.price for v in self.variants if v.is_enabled}

    def all_variant_ids(self) -> tuple[int, ...]:
        """Every variant the product carries, for the update coverage rule.
        The print areas say which, not ``variants``: naming a variant only
        ``variants`` lists gets 400 code 8251 (measured)."""
        named = {vid for area in self.print_areas for vid in area.variant_ids}
        return tuple(v.id for v in self.variants if v.id in named) or tuple(
            v.id for v in self.variants
        )


class ProductSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    description: str
    blueprint_id: int
    print_provider_id: int
    variants: dict[int, int]
    """``{variant_id: price}``, in minor units of the sales channel's currency
    (ADR-0019, ADR-0020 -- NOK passes through unconverted). The enabled set; anything
    absent is either untouched, on create, or explicitly disabled, on update."""
    print_areas: tuple[PrintAreaSpec, ...]
