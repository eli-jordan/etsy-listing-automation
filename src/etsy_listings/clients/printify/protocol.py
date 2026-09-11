"""The two Printify boundaries (A4). One host, one token, two authorities.

**This split is the whole point of having two protocols.** A caller that reads
reference data holds a :class:`CatalogClient` and cannot reach a call that
creates, updates or deletes anything -- not by discipline, but because the
method is not on the type it was handed. The plumbing underneath them is
shared (:mod:`~etsy_listings.clients.printify.transport`); the authority is
not, and that is the half worth keeping apart.

The two also differ in what may be done *with* a result. A catalog read is
large, rarely changes, is idempotent and is safe to cache on disk (PRD 22) and
to fan out (A3). A shop's products are the state this tool is converging on,
so a cached read of one would make ``plan`` diff against a stale world --
which is why :class:`~...cache.CachedCatalogClient` exists for one and
deliberately has no counterpart for the other.

Both surfaces are narrow, and grow one method at a time as a stage needs them
rather than in one speculative batch.
"""

from __future__ import annotations

from typing import Protocol

from etsy_listings.clients.printify.models import (
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
    """Printify's reference data: read-only and shop-agnostic (PRD 7b).

    Any implementation satisfies this without the rest of the codebase knowing
    which -- real HTTP, TTL-cached, or a test fake.
    """

    def blueprints(self) -> list[Blueprint]: ...

    def print_providers(self, blueprint_id: int) -> list[PrintProvider]: ...

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
        this protocol -- it is what tells you which shop to scope to (PRD 42)."""
        ...

    def upload_image(self, file_name: str, contents: bytes) -> Upload:
        """Upload a print file. Content-addressed: the same bytes always
        return the same id, so this is safe to repeat and merely wasteful."""
        ...

    def get_product(self, shop_id: int, product_id: str) -> Product | None:
        """The product, or ``None`` if it no longer exists."""
        ...

    def create_product(self, shop_id: int, spec: ProductSpec) -> Product: ...

    def update_product(
        self, shop_id: int, product_id: str, spec: ProductSpec, *, live: Product
    ) -> Product: ...

    def delete_product(self, shop_id: int, product_id: str) -> None: ...

    def publish(self, shop_id: int, product_id: str, sync_flags: dict[str, bool]) -> None:
        """Ask Printify to push this product to its connected sales channel.

        Fire-and-forget by design: Printify answers `200 {}` immediately and
        the actual publish happens asynchronously, behind `is_locked` --
        polling `get_product` is the caller's job (`publish` stage, A28)."""
        ...

    def publishing_failed(self, shop_id: int, product_id: str, *, reason: str) -> None:
        """Clear a publish lock stuck `is_locked: true` (PRD risk 6, `unlock`).
        Never verified against a genuinely stuck publish -- the lock is real,
        measured; the remedy is not."""
        ...

    def find_product_by_copy(self, shop_id: int, *, title: str, description: str) -> str | None:
        """The id of a product already carrying this copy, or ``None``.

        The duplicate-create guard (PRD 48). A walk of every product in the
        shop, matched client-side, because the list endpoint has no filter.
        """
        ...
