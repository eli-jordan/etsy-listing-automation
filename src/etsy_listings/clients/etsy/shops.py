"""Reading a shop's identity, sections and return policies.

Everything `setup` needs from Etsy and nothing that writes -- the protocol is
separate from the listing surface Phase 3's stages use for the reason A22
gives: authority is a property of the type, so a caller holding this one
cannot reach `updateListing` however the transport underneath is shared.

All four calls are **unscoped**. Etsy requires only the app key pair for them,
which is what lets `setup` resolve every id in `shop.yaml` before, or without,
a browser sign-in (PRD 49).
"""

from __future__ import annotations

from typing import Any, Protocol

from etsy_listings.clients.etsy.models import ReturnPolicy, Shop, ShopSection
from etsy_listings.clients.etsy.transport import HTTP_NOT_FOUND, EtsyApiError, Transport


class EtsyShopClient(Protocol):
    """What `setup` asks Etsy. Reads only, and shop-level only."""

    def find_shops(self, name: str) -> list[Shop]: ...

    def shop_by_owner(self, user_id: int) -> Shop | None: ...

    def shop_sections(self, shop_id: int) -> list[ShopSection]: ...

    def return_policies(self, shop_id: int) -> list[ReturnPolicy]: ...


class HttpEtsyShopClient:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def find_shops(self, name: str) -> list[Shop]:
        """Search by shop name. Etsy matches loosely, so the caller decides
        what counts as *the* match rather than trusting the first row."""
        response = self._transport.get("/v3/application/shops", params={"shop_name": name})
        return [Shop.model_validate(row) for row in _results(response.json())]

    def shop_by_owner(self, user_id: int) -> Shop | None:
        """The shop belonging to a user, or ``None`` if they have none.

        An Etsy account has at most one shop, and the user id is the prefix of
        the access token itself -- so this answers "which shop is the person
        who signed in selling from?" without asking them anything. A seller
        account with no shop yet is a real state, not an error: `404` there
        means "no shop", which is a question `setup` can ask about.
        """
        try:
            response = self._transport.get(f"/v3/application/users/{user_id}/shops")
        except EtsyApiError as exc:
            if exc.status_code == HTTP_NOT_FOUND:
                return None
            raise
        body = response.json()
        # Documented as a single Shop; a `results` list is what the sibling
        # search returns, and tolerating both costs one line.
        rows = _results(body)
        if rows:
            return Shop.model_validate(rows[0])
        return Shop.model_validate(body) if isinstance(body, dict) and "shop_id" in body else None

    def shop_sections(self, shop_id: int) -> list[ShopSection]:
        response = self._transport.get(f"/v3/application/shops/{shop_id}/sections")
        return [ShopSection.model_validate(row) for row in _results(response.json())]

    def return_policies(self, shop_id: int) -> list[ReturnPolicy]:
        response = self._transport.get(f"/v3/application/shops/{shop_id}/policies/return")
        return [ReturnPolicy.model_validate(row) for row in _results(response.json())]


def _results(body: Any) -> list[Any]:
    """Etsy's list envelope is always ``{count, results}``. Anything else is
    read as empty rather than raising: `setup` treats "no sections" and "a
    shape we did not expect" the same way -- it asks."""
    if isinstance(body, dict) and isinstance(body.get("results"), list):
        return list(body["results"])
    return []
