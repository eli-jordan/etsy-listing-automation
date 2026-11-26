"""Reading a shop's identity, sections and return policies."""

from __future__ import annotations

from typing import Protocol

from etsy_listings.core.clients.etsy.models import ReturnPolicy, Shop, ShopSection
from etsy_listings.core.clients.etsy.transport import (
    HTTP_NOT_FOUND,
    EtsyApiError,
    Transport,
    results_of,
)


class ShopMetadataClient(Protocol):
    def shop_sections(self, shop_id: int) -> list[ShopSection]: ...

    def return_policies(self, shop_id: int) -> list[ReturnPolicy]: ...


class EtsyShopClient(ShopMetadataClient, Protocol):
    def find_shops(self, name: str) -> list[Shop]: ...

    def shop_by_owner(self, user_id: int) -> Shop | None: ...


class ShopMetadataReads:
    _transport: Transport

    def shop_sections(self, shop_id: int) -> list[ShopSection]:
        response = self._transport.get(f"/v3/application/shops/{shop_id}/sections")
        return [ShopSection.model_validate(row) for row in results_of(response.json())]

    def return_policies(self, shop_id: int) -> list[ReturnPolicy]:
        response = self._transport.get(f"/v3/application/shops/{shop_id}/policies/return")
        return [ReturnPolicy.model_validate(row) for row in results_of(response.json())]


class HttpEtsyShopClient(ShopMetadataReads):
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def find_shops(self, name: str) -> list[Shop]:
        """Search by shop name. Etsy matches loosely, so the caller decides
        what counts as *the* match rather than trusting the first row."""
        response = self._transport.get("/v3/application/shops", params={"shop_name": name})
        return [Shop.model_validate(row) for row in results_of(response.json())]

    def shop_by_owner(self, user_id: int) -> Shop | None:
        """The user's one shop, or ``None``: Etsy answers 404 for a seller
        with no shop yet."""
        try:
            response = self._transport.get(f"/v3/application/users/{user_id}/shops")
        except EtsyApiError as exc:
            if exc.status_code == HTTP_NOT_FOUND:
                return None
            raise
        return Shop.model_validate(response.json())
