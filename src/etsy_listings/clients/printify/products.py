"""Printify's shop-scoped half over HTTP: the calls that write, and the ones
that read state a shop owns rather than reference data everyone shares.

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

The token, the retries and the error shapes are
:mod:`~etsy_listings.clients.printify.transport`, shared with the catalog
reader. What is *not* shared is the surface: reaching these calls means
holding a :class:`PrintifyClient`, which a caller that only reads the catalog
never does.
"""

from __future__ import annotations

import base64
from typing import Any

from etsy_listings.clients.printify.models import (
    PrintAreaSpec,
    Product,
    ProductSpec,
    Shop,
    Upload,
)
from etsy_listings.clients.printify.protocol import PrintifyClient
from etsy_listings.clients.printify.transport import (
    HTTP_NOT_FOUND,
    WRONG_SHOP_CODE,
    PrintifyApiError,
    Transport,
)

PRODUCTS_PAGE_SIZE = 50


class HttpPrintifyClient(PrintifyClient):
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def shops(self) -> list[Shop]:
        response = self._transport.request("GET", "/v1/shops.json")
        return [Shop.model_validate(item) for item in response.json()]

    # ------------------------------------------------------------- uploads

    def upload_image(self, file_name: str, contents: bytes) -> Upload:
        response = self._transport.request(
            "POST",
            "/v1/uploads/images.json",
            json={
                "file_name": file_name,
                "contents": base64.b64encode(contents).decode("ascii"),
            },
        )
        return Upload.model_validate(response.json())

    # ------------------------------------------------------------ products

    def get_product(self, shop_id: int, product_id: str) -> Product | None:
        """The product, or ``None`` if this shop does not have it.

        Deleted in Printify's web app between runs is an ordinary thing to
        happen, and it means "create one", not "crash".

        Two answers mean the same thing here. `404` is the id nothing knows,
        and `400`/:data:`~etsy_listings.clients.printify.transport.WRONG_SHOP_CODE`
        is the id another shop holds -- which, from this shop's side, is the
        same absence. Catching only the first turns reconnecting a store into
        a hard failure on the next `plan`, because the lockfile still names
        the product the old shop had.
        """
        try:
            response = self._transport.request(
                "GET", f"/v1/shops/{shop_id}/products/{product_id}.json"
            )
        except PrintifyApiError as exc:
            if exc.status_code == HTTP_NOT_FOUND or exc.code == WRONG_SHOP_CODE:
                return None
            raise
        return Product.model_validate(response.json())

    def create_product(self, shop_id: int, spec: ProductSpec) -> Product:
        """Create, hidden.

        ``visible: false`` because a product nobody has reviewed has no
        business being visible, and the field *is* writable despite the API
        reference marking it read-only (docs/api-findings.md).
        """
        body = {
            "title": spec.title,
            "description": spec.description,
            "blueprint_id": spec.blueprint_id,
            "print_provider_id": spec.print_provider_id,
            # On create the print areas cover only the variants being created.
            # On update they must cover every variant the product has -- see
            # `update_product`.
            "variants": _variant_bodies(spec.variants, retiring={}),
            "print_areas": _print_area_bodies(spec.print_areas),
            "visible": False,
        }
        response = self._transport.request("POST", f"/v1/shops/{shop_id}/products.json", json=body)
        return Product.model_validate(response.json())

    def update_product(
        self, shop_id: int, product_id: str, spec: ProductSpec, *, live: Product
    ) -> Product:
        """Update, taking ``live`` because an update cannot be built without it.

        Two measured rules make this differ from create rather than share it:

        - **``variants`` merges by id.** Omitting one does not disable it, so a
          colour the listing dropped has to be named with an explicit
          ``is_enabled: false`` -- and carry a price, because a variant entry
          is never partial.
        - **``print_areas.variant_ids`` must cover every variant the product
          has**, not the ones being changed. The payload that created the
          product is rejected as an update of it (400 code 8251).
        """
        retiring = {
            variant.id: variant.price
            for variant in live.variants
            if variant.is_enabled and variant.id not in spec.variants
        }
        body = {
            "title": spec.title,
            "description": spec.description,
            "variants": _variant_bodies(spec.variants, retiring=retiring),
            "print_areas": _print_area_bodies(spec.print_areas, cover=live.all_variant_ids()),
        }
        response = self._transport.request(
            "PUT", f"/v1/shops/{shop_id}/products/{product_id}.json", json=body
        )
        return Product.model_validate(response.json())

    def delete_product(self, shop_id: int, product_id: str) -> None:
        self._transport.request("DELETE", f"/v1/shops/{shop_id}/products/{product_id}.json")

    def publish(self, shop_id: int, product_id: str, sync_flags: dict[str, bool]) -> None:
        self._transport.request(
            "POST", f"/v1/shops/{shop_id}/products/{product_id}/publish.json", json=sync_flags
        )

    def publishing_failed(self, shop_id: int, product_id: str, *, reason: str) -> None:
        self._transport.request(
            "POST",
            f"/v1/shops/{shop_id}/products/{product_id}/publishing_failed.json",
            json={"reason": reason},
        )

    def find_product_by_copy(self, shop_id: int, *, title: str, description: str) -> str | None:
        """The id of a product already carrying this copy, or ``None``. PRD 48.

        A walk, not a query: ``GET products.json`` accepts ``title``,
        ``search`` and ``sku`` and ignores all three, so the match is
        client-side over every page. Affordable because it runs only where a
        create is already pending -- never on a no-op ``plan``.

        Deleted products stay in the listing, and adopting one would bind the
        lockfile to a product that can no longer be updated.
        """
        page = 1
        while True:
            response = self._transport.request(
                "GET",
                f"/v1/shops/{shop_id}/products.json",
                params={"page": page, "limit": PRODUCTS_PAGE_SIZE},
            )
            body = response.json()
            for raw in body.get("data", []):
                if raw.get("is_deleted"):
                    continue
                if raw.get("title") == title and raw.get("description") == description:
                    return str(raw["id"])
            if page >= int(body.get("last_page", page)):
                return None
            page += 1


def _variant_bodies(variants: dict[int, int], *, retiring: dict[int, int]) -> list[dict[str, Any]]:
    """Enabled variants, plus explicit disables for the ones being retired.

    **Every entry carries a price, including a disabled one.** Measured:
    ``{"id": ..., "is_enabled": false}`` alone is
    ``400 8150 "variants.0.price: The variants.0.price field is required."``
    A variant entry is never partial, which is also why the lockfile has to
    remember what each enabled variant cost -- the desired document cannot
    supply a price for a colour it no longer offers.
    """
    bodies = [
        {"id": variant_id, "price": price, "is_enabled": True}
        for variant_id, price in variants.items()
    ]
    bodies.extend(
        {"id": variant_id, "price": price, "is_enabled": False}
        for variant_id, price in retiring.items()
    )
    return bodies


def _print_area_bodies(
    areas: tuple[PrintAreaSpec, ...], *, cover: tuple[int, ...] | None = None
) -> list[dict[str, Any]]:
    """Print areas as Printify wants them, optionally widened to ``cover``.

    ``cover`` is the update coverage rule: the union across all entries must
    name every variant the product has. Widening the **last** area rather than
    spreading the extras keeps every earlier area's variant set exactly as the
    caller partitioned it, which is what PRD 30's on-light/on-dark split
    depends on -- a dark-ink group that quietly gained the whole matrix would
    print the wrong file on half the shirts.
    """
    bodies: list[dict[str, Any]] = [
        {
            "variant_ids": list(area.variant_ids),
            "placeholders": [
                {
                    "position": placeholder.position,
                    "images": [image.model_dump() for image in placeholder.images],
                }
                for placeholder in area.placeholders
            ],
        }
        for area in areas
    ]
    if cover is not None and bodies:
        named = {vid for body in bodies for vid in body["variant_ids"]}
        bodies[-1]["variant_ids"] = sorted(set(bodies[-1]["variant_ids"]) | (set(cover) - named))
    return bodies
