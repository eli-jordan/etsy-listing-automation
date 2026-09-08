"""The shop-scoped Printify write boundary (A4).

Narrow by design: methods land as a stage needs them, not in one speculative
batch. ``shops()`` came first because every other call here is scoped to a
shop id, and that one discovers it (PRD 42).

``update_product`` takes the live product rather than fetching it, which looks
redundant and is not. Printify's update coverage rule needs every variant the
product carries, and the retire path needs the price of each variant being
switched off -- both only knowable from a read. Passing it in keeps the read
where the caller can see it happen, instead of hiding a second round trip
inside a write.
"""

from __future__ import annotations

from typing import Protocol

from etsy_listings.clients.printify.models import Product, ProductSpec, Shop, Upload


class PrintifyClient(Protocol):
    def shops(self) -> list[Shop]:
        """Every shop the token can reach. Not shop-scoped, unlike the rest of
        this protocol -- it is what tells you which shop to scope to."""
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

    def find_product_by_copy(self, shop_id: int, *, title: str, description: str) -> str | None:
        """The id of a product already carrying this copy, or ``None``.

        The duplicate-create guard (PRD 48). A walk of every product in the
        shop, matched client-side, because the list endpoint has no filter.
        """
        ...
