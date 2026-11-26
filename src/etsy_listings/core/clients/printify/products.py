"""Printify's shop-scoped half over HTTP: the calls that write, and the ones
that read state a shop owns rather than reference data everyone shares."""

from __future__ import annotations

import base64
from typing import Any

from etsy_listings.core.clients.printify.models import (
    PrintAreaSpec,
    Product,
    ProductSpec,
    Shop,
    Upload,
)
from etsy_listings.core.clients.printify.protocol import PrintifyClient
from etsy_listings.core.clients.printify.transport import (
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

    def get_product(self, shop_id: int, product_id: str) -> Product | None:
        """The product, or ``None`` if this shop does not have it: deleted in
        Printify's web app between runs means "create one", not "crash"."""
        try:
            response = self._transport.request(
                "GET", f"/v1/shops/{shop_id}/products/{product_id}.json"
            )
        except PrintifyApiError as exc:
            if _is_absent(exc):
                return None
            raise
        return Product.model_validate(response.json())

    def create_product(self, shop_id: int, spec: ProductSpec) -> Product:
        body = {
            "title": spec.title,
            "description": spec.description,
            "blueprint_id": spec.blueprint_id,
            "print_provider_id": spec.print_provider_id,
            "variants": _variant_bodies(spec.variants, retiring={}),
            "print_areas": _print_area_bodies(spec.print_areas),
            "visible": False,
        }
        response = self._transport.request("POST", f"/v1/shops/{shop_id}/products.json", json=body)
        return Product.model_validate(response.json())

    def update_product(
        self, shop_id: int, product_id: str, spec: ProductSpec, *, live: Product
    ) -> Product:
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
        try:
            self._transport.request("DELETE", f"/v1/shops/{shop_id}/products/{product_id}.json")
        except PrintifyApiError as exc:
            if _is_absent(exc):
                return
            raise

    def set_visible(self, shop_id: int, product_id: str, *, visible: bool) -> None:
        self._transport.request(
            "PUT", f"/v1/shops/{shop_id}/products/{product_id}.json", json={"visible": visible}
        )

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
        page = 1
        while True:
            response = self._transport.request(
                "GET",
                f"/v1/shops/{shop_id}/products.json",
                params={"page": page, "limit": PRODUCTS_PAGE_SIZE},
            )
            body = response.json()
            found = _product_with_copy(body.get("data", []), title=title, description=description)
            if found is not None:
                return found
            if page >= int(body.get("last_page", page)):
                return None
            page += 1


def _is_absent(exc: PrintifyApiError) -> bool:
    return exc.status_code == HTTP_NOT_FOUND or exc.code == WRONG_SHOP_CODE


def _product_with_copy(
    products: list[dict[str, Any]], *, title: str, description: str
) -> str | None:
    for raw in products:
        if raw.get("is_deleted"):
            continue
        if raw.get("title") == title and raw.get("description") == description:
            return str(raw["id"])
    return None


def _variant_bodies(variants: dict[int, int], *, retiring: dict[int, int]) -> list[dict[str, Any]]:
    bodies = [
        {"id": variant_id, "price": price, "is_enabled": True}
        for variant_id, price in variants.items()
    ]
    bodies.extend(
        {"id": variant_id, "price": price, "is_enabled": False}
        for variant_id, price in retiring.items()
    )
    return bodies


def _print_area_body(area: PrintAreaSpec) -> dict[str, Any]:
    return {
        "variant_ids": list(area.variant_ids),
        "placeholders": [
            {
                "position": placeholder.position,
                "images": [image.model_dump() for image in placeholder.images],
            }
            for placeholder in area.placeholders
        ],
    }


def _print_area_bodies(
    areas: tuple[PrintAreaSpec, ...], *, cover: tuple[int, ...] | None = None
) -> list[dict[str, Any]]:
    """Print areas as Printify wants them, optionally widened to ``cover``.

    ``cover`` is the update coverage rule: the union across all entries must
    name every variant the product has. Widening the **last** area rather than
    spreading the extras keeps every earlier area's variant set exactly as the
    caller partitioned it, which is what on-light/on-dark split
    depends on -- a dark-ink group that quietly gained the whole matrix would
    print the wrong file on half the shirts.
    """
    bodies = [_print_area_body(area) for area in areas]
    if cover is not None and bodies:
        named = {vid for body in bodies for vid in body["variant_ids"]}
        bodies[-1]["variant_ids"] = sorted(set(bodies[-1]["variant_ids"]) | (set(cover) - named))
    return bodies
