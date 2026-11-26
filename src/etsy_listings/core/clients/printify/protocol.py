"""The two Printify boundaries. One host, one token, two authorities."""

from __future__ import annotations

from typing import Protocol

from etsy_listings.core.clients.printify.models import (
    Blueprint,
    PrintProvider,
    Product,
    ProductSpec,
    ShippingRates,
    Shop,
    Upload,
    VariantSet,
)


class CatalogClient(Protocol):
    def blueprints(self) -> list[Blueprint]: ...

    def print_providers(self, blueprint_id: int) -> list[PrintProvider]: ...

    def all_print_providers(self) -> list[PrintProvider]:
        """Every provider in the catalog, whatever it prints: what a seller
        may prefer before any garment is chosen (Admin plan, *Shop*)."""
        ...

    def variants(self, blueprint_id: int, provider_id: int) -> VariantSet: ...

    def shipping(self, blueprint_id: int, provider_id: int) -> ShippingRates: ...


class PrintifyClient(Protocol):
    """Printify's shop-scoped half: the calls that write, and the ones that
    read state a shop owns.

    ``update_product`` takes the live product rather than fetching it, which
    looks redundant and is not. Printify's update coverage rule needs every
    variant the product carries, and the retire path needs the price of each
    variant being switched off -- both only knowable from a read. Passing it
    in keeps the read where the caller can see it happen, instead of hiding a
    second round trip inside a write.
    """

    def shops(self) -> list[Shop]:
        """Every shop the token can reach. Not shop-scoped, unlike the rest of
        this protocol -- it is what tells you which shop to scope to."""
        ...

    def upload_image(self, file_name: str, contents: bytes) -> Upload:
        """Upload a print file. Content-addressed: the same bytes always
        return the same id, so this is safe to repeat and merely wasteful."""
        ...

    def get_product(self, shop_id: int, product_id: str) -> Product | None: ...

    def create_product(self, shop_id: int, spec: ProductSpec) -> Product: ...

    def update_product(
        self, shop_id: int, product_id: str, spec: ProductSpec, *, live: Product
    ) -> Product: ...

    def delete_product(self, shop_id: int, product_id: str) -> None:
        """Remove the product. Idempotent: already gone is success, not an error."""
        ...

    def set_visible(self, shop_id: int, product_id: str, *, visible: bool) -> None: ...

    def publish(self, shop_id: int, product_id: str, sync_flags: dict[str, bool]) -> None:
        """Ask Printify to push this product to its connected sales channel.

        Fire-and-forget by design: Printify answers `200 {}` immediately and
        the actual publish happens asynchronously, behind `is_locked` --
        polling `get_product` is the caller's job (`publish` stage)."""
        ...

    def publishing_failed(self, shop_id: int, product_id: str, *, reason: str) -> None:
        """Clear a publish lock stuck `is_locked: true` (`unlock`).
        Never verified against a genuinely stuck publish -- the lock is real,
        measured; the remedy is not."""
        ...

    def find_product_by_copy(self, shop_id: int, *, title: str, description: str) -> str | None: ...
