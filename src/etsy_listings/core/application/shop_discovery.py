from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from etsy_listings.core import connections
from etsy_listings.core.clients.etsy.models import ReturnPolicy
from etsy_listings.core.clients.etsy.models import Shop as EtsyShop
from etsy_listings.core.clients.etsy.shops import EtsyShopClient
from etsy_listings.core.clients.printify.models import Shop

FALLBACK_CURRENCY = "NOK"


@dataclass(frozen=True)
class NeedsChoice: ...


@dataclass(frozen=True)
class NoShops:
    problem: str


ShopSelection = Shop | NeedsChoice | NoShops


def select_shop(shops: Sequence[Shop]) -> ShopSelection:
    if not shops:
        return NoShops(
            "this Printify account has no shops, so there is nowhere to create "
            "products. Create one at printify.com (My stores -> Add new store); "
            "an 'API' store is enough for everything up to publishing."
        )
    if len(shops) == 1:
        return shops[0]
    return NeedsChoice()


@dataclass(frozen=True)
class EtsyAccess:
    client: EtsyShopClient
    user_id: int | None


def etsy_access(root: Path, shop_client: Callable[[Path], EtsyShopClient]) -> EtsyAccess | None:
    if connections.etsy_app_key(root) is None:
        return None
    tokens = connections.etsy_token_store(root).load()
    return EtsyAccess(shop_client(root), tokens.user_id if tokens else None)


def exact_shop_match(candidates: Sequence[EtsyShop], name: str) -> EtsyShop | None:
    """Etsy's shop search matches loosely: only one exact match (case aside) counts."""
    matches = [shop for shop in candidates if shop.shop_name.casefold() == name.casefold()]
    return matches[0] if len(matches) == 1 else None


@dataclass(frozen=True)
class FoundShop:
    shop: EtsyShop
    route: Literal["connected", "owner"]
    """``connected``: named after the connected Printify shop. ``owner``: the
    signed-in Etsy account's shop."""


def find_etsy_shop(access: EtsyAccess, printify_shop: Shop) -> FoundShop | None:
    """Printify names a connected shop after the Etsy shop it publishes to."""
    if printify_shop.is_connected:
        matches = access.client.find_shops(printify_shop.title)
        found = exact_shop_match(matches, printify_shop.title)
        if found is not None:
            return FoundShop(found, "connected")

    if access.user_id is not None:
        owned = access.client.shop_by_owner(access.user_id)
        if owned is not None:
            return FoundShop(owned, "owner")
    return None


@dataclass(frozen=True)
class ShopLookup:
    exact: EtsyShop | None
    candidates: tuple[EtsyShop, ...]


def lookup_etsy_shop(client: EtsyShopClient, name: str) -> ShopLookup:
    matches = client.find_shops(name)
    return ShopLookup(exact=exact_shop_match(matches, name), candidates=tuple(matches))


def policy_terms(policy: ReturnPolicy) -> dict[str, Any]:
    return {
        "accepts_returns": bool(policy.accepts_returns),
        "accepts_exchanges": bool(policy.accepts_exchanges),
        "within_days": policy.return_deadline,
    }


@dataclass(frozen=True)
class ReturnPolicyOptions:
    policies: tuple[ReturnPolicy, ...]
    """The one ``shop.yaml`` already names first."""
    current: dict[str, Any] | None

    def is_current(self, policy: ReturnPolicy) -> bool:
        return self.current is not None and policy_terms(policy) == self.current


def return_policy_options(
    client: EtsyShopClient, shop: EtsyShop, current: dict[str, Any] | None
) -> ReturnPolicyOptions:
    policies = client.return_policies(shop.shop_id)
    options = ReturnPolicyOptions(policies=(), current=current)
    ordered = sorted(policies, key=lambda policy: not options.is_current(policy))
    return ReturnPolicyOptions(policies=tuple(ordered), current=current)


def currency_default(etsy_shop: EtsyShop | None, existing_etsy: dict[str, Any]) -> str:
    if etsy_shop is not None and etsy_shop.currency_code:
        return etsy_shop.currency_code
    return str(existing_etsy.get("currency") or FALLBACK_CURRENCY)
