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
    read state a shop owns. ``update_product`` takes the ``live`` product
    because Printify's update coverage rule needs every variant it carries.
    """

    def shops(self) -> list[Shop]:
        """Every shop the token can reach; the one call not shop-scoped."""
        ...

    def upload_image(self, file_name: str, contents: bytes) -> Upload:
        """Upload a print file. Printify content-addresses uploads, so a repeat
        returns the same id."""
        ...

    def get_product(self, shop_id: int, product_id: str) -> Product | None: ...

    def create_product(self, shop_id: int, spec: ProductSpec) -> Product: ...

    def update_product(
        self, shop_id: int, product_id: str, spec: ProductSpec, *, live: Product
    ) -> Product: ...

    def delete_product(self, shop_id: int, product_id: str) -> None: ...

    def set_visible(self, shop_id: int, product_id: str, *, visible: bool) -> None: ...

    def publish(self, shop_id: int, product_id: str, sync_flags: dict[str, bool]) -> None:
        """Ask Printify to push this product to its sales channel. Printify
        answers `200 {}` at once and publishes behind `is_locked`; the caller polls."""
        ...

    def publishing_failed(self, shop_id: int, product_id: str, *, reason: str) -> None:
        """Clear a publish lock stuck `is_locked: true`. Unverified against a
        genuinely stuck publish."""
        ...

    def find_product_by_copy(self, shop_id: int, *, title: str, description: str) -> str | None: ...
