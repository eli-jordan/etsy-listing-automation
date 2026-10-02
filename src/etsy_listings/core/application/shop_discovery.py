"""Finding the shops a workspace publishes to, from the credentials it holds.

``setup`` discovers ids rather than asking for them (ADR-0025): the Printify
shop from the token's own shop list, the Etsy shop by the cheapest route that
is certain, and the return policy by its terms. Everything here answers with
what it found -- or that it found nothing certain -- and leaves the question
to the caller, which for ``setup`` is the CLI (``cli/setup.py``). Clients
arrive as arguments, so discovery runs against fakes with no network.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from etsy_listings.core import connections
from etsy_listings.core.clients.etsy.models import ReturnPolicy
from etsy_listings.core.clients.etsy.models import Shop as EtsyShop
from etsy_listings.core.clients.etsy.shops import EtsyShopClient
from etsy_listings.core.clients.printify.models import Shop

# ------------------------------------------------------------------- Printify


@dataclass(frozen=True)
class ShopSelection:
    """The outcome of asking Printify which shops a token can reach.

    Three outcomes, not two: exactly one shop answers the question outright,
    several make it a question for the user, and none is a problem no prompt
    can fix.
    """

    shop: Shop | None = None
    needs_choice: bool = False
    problem: str | None = None


def select_shop(shops: Sequence[Shop]) -> ShopSelection:
    if not shops:
        return ShopSelection(
            problem=(
                "this Printify account has no shops, so there is nowhere to create "
                "products. Create one at printify.com (My stores -> Add new store); "
                "an 'API' store is enough for everything up to publishing."
            )
        )
    if len(shops) == 1:
        return ShopSelection(shop=shops[0])
    return ShopSelection(needs_choice=True)


# ----------------------------------------------------------------------- Etsy


@dataclass(frozen=True)
class EtsyAccess:
    """A client that can read Etsy, and who it is reading as.

    ``user_id`` is ``None`` when the app key pair is stored but nobody has
    signed in: the searches still work -- they are unscoped -- but "which shop
    does the signed-in seller own?" has no answer, so discovery falls back to
    asking for a name.
    """

    client: EtsyShopClient
    user_id: int | None


def etsy_access(root: Path) -> EtsyAccess | None:
    """Etsy access from what the workspace has stored, or ``None`` when it
    holds no app key pair -- which is every workspace before ``auth etsy``,
    and must not stop ``setup`` from writing one.

    The client is ``connections``' shop client, as for every other Etsy
    caller: discovery's calls are unscoped, and that client adds the bearer
    only when someone has signed in -- which is what makes ``shop_by_owner``
    possible.
    """
    if connections.etsy_app_key(root) is None:
        return None
    tokens = connections.etsy_token_store(root).load()
    return EtsyAccess(connections.etsy_shop_client(root), tokens.user_id if tokens else None)


def exact_shop_match(candidates: Sequence[EtsyShop], name: str) -> EtsyShop | None:
    """The one shop whose name *is* ``name``, or ``None``.

    Etsy's shop search matches loosely -- it is built for buyers browsing, not
    for resolving an identifier -- so "TakeAHike" can come back alongside
    "TakeAHikeVintage" and a dozen others. Taking the first row would give a
    workspace that publishes to a stranger's shop, so anything less certain
    than a single exact match (case aside) is treated as no answer at all and
    put in front of the user.
    """
    matches = [shop for shop in candidates if shop.shop_name.casefold() == name.casefold()]
    return matches[0] if len(matches) == 1 else None


@dataclass(frozen=True)
class FoundShop:
    shop: EtsyShop
    route: Literal["connected", "owner"]
    """``connected``: named after the connected Printify shop. ``owner``: the
    shop the signed-in Etsy account owns."""


def find_etsy_shop(access: EtsyAccess, printify_shop: Shop) -> FoundShop | None:
    """The Etsy shop by the two certain routes, cheapest first, or ``None``.

    A connected Printify shop is the best evidence available: Printify names
    the shop after the Etsy shop it publishes to, so the selection the user
    just made *is* the answer. Failing that, an Etsy account owns exactly one
    shop, and the stored consent says which account. Only if both are silent
    does anyone need to be asked for a name -- the caller's job.

    Etsy errors propagate: whether one is fatal is the caller's call.
    """
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
    """Everything the search returned, for a caller offering a choice when
    there is no exact match."""


def lookup_etsy_shop(client: EtsyShopClient, name: str) -> ShopLookup:
    """Resolve a typed shop name to an id by searching for it.

    The id is never asked for, because a number typed by hand is the thing
    discovery exists to avoid.
    """
    matches = client.find_shops(name)
    return ShopLookup(exact=exact_shop_match(matches, name), candidates=tuple(matches))


def policy_terms(policy: ReturnPolicy) -> dict[str, Any]:
    """The three terms a return policy is addressed by in ``shop.yaml``,
    since Etsy gives the resource no title."""
    return {
        "accepts_returns": bool(policy.accepts_returns),
        "accepts_exchanges": bool(policy.accepts_exchanges),
        "within_days": policy.return_deadline,
    }


@dataclass(frozen=True)
class ReturnPolicyOptions:
    policies: tuple[ReturnPolicy, ...]
    """The shop's policies, the one ``shop.yaml`` already names first."""
    current: dict[str, Any] | None

    def is_current(self, policy: ReturnPolicy) -> bool:
        return self.current is not None and policy_terms(policy) == self.current


def return_policy_options(
    client: EtsyShopClient, shop: EtsyShop, current: dict[str, Any] | None
) -> ReturnPolicyOptions:
    """The shop's return policies, for a caller deciding whether to ask.

    None means listings are drafted without one; exactly one needs no
    reference at all -- the stages resolve it live the same way. Only two or
    more make it a question, answered by the policy's *terms*.
    """
    policies = client.return_policies(shop.shop_id)
    options = ReturnPolicyOptions(policies=(), current=current)
    ordered = sorted(policies, key=lambda policy: not options.is_current(policy))
    return ReturnPolicyOptions(policies=tuple(ordered), current=current)


def currency_default(etsy_shop: EtsyShop | None, existing_etsy: dict[str, Any]) -> str:
    """The Etsy shop's own currency wins, then the file, then NOK.

    The shop's answer goes first because it is the only one that cannot be
    wrong: a workspace configured in a currency the shop does not sell in is a
    disagreement nothing surfaces until a price lands wrong. It is still only
    a default -- the caller offers it, and the user can say otherwise.
    """
    if etsy_shop is not None and etsy_shop.currency_code:
        return etsy_shop.currency_code
    return str(existing_etsy.get("currency") or "NOK")
