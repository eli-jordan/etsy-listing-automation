"""In-memory Etsy, for the behaviour layer (A4).

Behaviour tests drive this; contract tests drive the HTTP client through
`httpx`'s mock transport against transcripts. Asking either to do the other's
job is the mistake that split exists to prevent.
"""

from __future__ import annotations

from etsy_listings.clients.etsy.models import ReturnPolicy, Shop, ShopSection


class FakeEtsyShopClient:
    """Every read `setup` makes, answered from a dict.

    `find_shops` matches case-insensitively on the whole name rather than as a
    substring: what it stands in for is Etsy's own search, and the caller's
    job is to decide whether a result really is the shop it asked about.
    """

    def __init__(
        self,
        shops: list[Shop] | None = None,
        *,
        owned: Shop | None = None,
        sections: list[ShopSection] | None = None,
        policies: list[ReturnPolicy] | None = None,
    ) -> None:
        self._shops = list(shops or [])
        self._owned = owned
        self._sections = list(sections or [])
        self._policies = list(policies or [])
        self.searched: list[str] = []
        self.owner_lookups: list[int] = []

    def find_shops(self, name: str) -> list[Shop]:
        self.searched.append(name)
        return [shop for shop in self._shops if shop.shop_name.lower() == name.lower()]

    def shop_by_owner(self, user_id: int) -> Shop | None:
        self.owner_lookups.append(user_id)
        return self._owned

    def shop_sections(self, shop_id: int) -> list[ShopSection]:
        return list(self._sections)

    def return_policies(self, shop_id: int) -> list[ReturnPolicy]:
        return list(self._policies)
