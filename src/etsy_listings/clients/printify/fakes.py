"""In-memory :class:`PrintifyClient` for behaviour tests. No network, ever.

It models the API's *awkward* behaviour, not a tidy version of it, because the
awkward parts are what the stage exists to handle: a created product comes
back carrying the whole blueprint matrix with everything but the requested
variants disabled, and an update merges variants by id rather than replacing
them. A fake that behaved sensibly would let a stage pass its tests and fail
against Printify (A4 -- reach for a fake to test behaviour, a cassette to test
payload shape).
"""

from __future__ import annotations

import hashlib

from etsy_listings.clients.printify.http import PrintifyAuthError
from etsy_listings.clients.printify.models import (
    Product,
    ProductSpec,
    ProductVariant,
    Shop,
    Upload,
)
from etsy_listings.clients.printify.protocol import PrintifyClient

BLUEPRINT_MATRIX_PADDING = (900001, 900002, 900003)
"""Variant ids no test asks for, present on every product this fake creates.

The real API returns 238 variants for a product created with 6. Three is
enough to make the same mistakes fail: a comparison against the raw variant
list, or an update whose print areas cover only what changed.
"""


class FakePrintifyClient(PrintifyClient):
    def __init__(
        self,
        shops: list[Shop] | None = None,
        *,
        auth_fails: bool = False,
    ) -> None:
        self._shops = list(shops or [])
        self.auth_fails = auth_fails
        self.products: dict[str, Product] = {}
        self.uploads: dict[str, bytes] = {}
        self.shops_calls = 0
        self.created: list[ProductSpec] = []
        self.updated: list[ProductSpec] = []
        self.deleted: list[str] = []
        self._next_product = 0

    # ------------------------------------------------------------- shops

    def shops(self) -> list[Shop]:
        self.shops_calls += 1
        if self.auth_fails:
            raise PrintifyAuthError(401)
        return list(self._shops)

    # ----------------------------------------------------------- uploads

    def upload_image(self, file_name: str, contents: bytes) -> Upload:
        """Content-addressed, like the real one: the same bytes give the same
        id, and the file name takes no part in it. A stage that re-uploads
        needlessly is a stage wasting megabytes, and only this property makes
        that visible in a test."""
        upload_id = hashlib.sha256(contents).hexdigest()[:24]
        self.uploads[upload_id] = contents
        return Upload(id=upload_id, file_name=file_name, width=4200, height=4800)

    # ---------------------------------------------------------- products

    def get_product(self, shop_id: int, product_id: str) -> Product | None:
        return self.products.get(product_id)

    def create_product(self, shop_id: int, spec: ProductSpec) -> Product:
        self._next_product += 1
        product_id = f"fake-product-{self._next_product}"
        product = Product(
            id=product_id,
            title=spec.title,
            description=spec.description,
            blueprint_id=spec.blueprint_id,
            print_provider_id=spec.print_provider_id,
            variants=self._matrix(spec.variants),
            print_areas=spec.print_areas,
            visible=False,
        )
        self.products[product_id] = product
        self.created.append(spec)
        return product

    def update_product(
        self, shop_id: int, product_id: str, spec: ProductSpec, *, live: Product
    ) -> Product:
        """Merges variants by id, exactly as measured: a variant absent from
        the spec keeps whatever it had. Only the caller's explicit disables
        retire anything, which is the behaviour the retire path has to get
        right."""
        merged = {variant.id: (variant.price, variant.is_enabled) for variant in live.variants}
        for variant_id, price in spec.variants.items():
            merged[variant_id] = (price, True)
        for variant in live.variants:
            if variant.is_enabled and variant.id not in spec.variants:
                merged[variant.id] = (merged[variant.id][0], False)

        product = live.model_copy(
            update={
                "title": spec.title,
                "description": spec.description,
                "variants": tuple(
                    ProductVariant(id=vid, price=price, is_enabled=enabled)
                    for vid, (price, enabled) in merged.items()
                ),
                "print_areas": spec.print_areas,
            }
        )
        self.products[product_id] = product
        self.updated.append(spec)
        return product

    def delete_product(self, shop_id: int, product_id: str) -> None:
        self.products.pop(product_id, None)
        self.deleted.append(product_id)

    def find_product_by_copy(self, shop_id: int, *, title: str, description: str) -> str | None:
        for product in self.products.values():
            if (
                not product.is_deleted
                and product.title == title
                and product.description == description
            ):
                return product.id
        return None

    @staticmethod
    def _matrix(wanted: dict[int, int]) -> tuple[ProductVariant, ...]:
        enabled = [
            ProductVariant(id=vid, price=price, is_enabled=True, cost=1304)
            for vid, price in wanted.items()
        ]
        padding = [
            ProductVariant(id=vid, price=1304, is_enabled=False, cost=1304)
            for vid in BLUEPRINT_MATRIX_PADDING
            if vid not in wanted
        ]
        return tuple(enabled + padding)
