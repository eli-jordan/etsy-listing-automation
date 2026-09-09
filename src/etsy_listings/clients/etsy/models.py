"""The Etsy responses this tool reads, narrowed to the fields it uses.

Etsy's `Shop` carries forty-seven fields, most of them about a storefront's
presentation. Modelling all of them would make every one of them look load
bearing, and would turn a field Etsy renames into a validation error in a
workspace that never touched it. So: the few we act on, and `extra="ignore"`
for the rest.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Shop(BaseModel):
    """An Etsy shop, as `findShops` and `getShopByOwnerUserId` return it.

    `currency_code` is the reason this model exists beyond the id: it is the
    shop's own currency, and reading it is what stops a workspace being
    configured in one currency while the shop sells in another (PRD 51).
    """

    model_config = ConfigDict(extra="ignore")

    shop_id: int
    shop_name: str
    currency_code: str | None = None
    user_id: int | None = None
    url: str | None = None


class ShopSection(BaseModel):
    """A section a listing can be filed under (`etsy.shop_section_id`)."""

    model_config = ConfigDict(extra="ignore")

    shop_section_id: int
    title: str
    active_listing_count: int | None = None


class ReturnPolicy(BaseModel):
    """A listing-level return policy (`etsy.return_policy_id`).

    Etsy gives these no title, so the only way to tell two apart is the terms
    themselves -- which is why all three fields are carried rather than the id
    alone: a picker offering "1122334" and "1122335" would be a coin toss.
    """

    model_config = ConfigDict(extra="ignore")

    return_policy_id: int
    accepts_returns: bool | None = None
    accepts_exchanges: bool | None = None
    return_deadline: int | None = None

    def describe(self) -> str:
        if self.accepts_returns is None and self.accepts_exchanges is None:
            return f"policy {self.return_policy_id}"
        accepted = [
            name
            for name, allowed in (
                ("returns", self.accepts_returns),
                ("exchanges", self.accepts_exchanges),
            )
            if allowed
        ]
        if not accepted:
            return "no returns or exchanges"
        within = f" within {self.return_deadline} days" if self.return_deadline else ""
        return f"{' and '.join(accepted)}{within}"
