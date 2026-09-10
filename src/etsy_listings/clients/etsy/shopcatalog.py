"""Per-run name -> id resolution for the four things `shop.yaml`/
`listing.yaml` refer to by name rather than by Etsy's own id (decision 2,
PRD 53/54/59).

Resolution happens **once per run, in memory** -- not disk-cached like
Printify's catalog (A25). A stale section id fails the *whole* PATCH, and the
three lists here are small, shop-scoped and cheap to re-fetch next run, so
there is nothing a cache would buy and one thing it would cost: a renamed
section in Shop Manager staying invisible until the cache expired.

Three of the four are name -> single-field lookups. The fourth, a
production partner, is a resolution *ladder* (decision 3): named, then the
shop's only one, then an error naming every candidate -- because guessing
which partner or which return policy is meant is not something this tool
should do with a fulfilment relationship or a refund policy.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from etsy_listings.clients.etsy.listings import EtsyListingClient
from etsy_listings.clients.etsy.models import (
    ProductionPartner,
    ReturnPolicy,
    ShippingProfile,
    ShopSection,
)
from etsy_listings.clients.etsy.shops import EtsyShopClient
from etsy_listings.clients.printify.resolve import normalise
from etsy_listings.errors import UserFacingError

SHOP_MANAGER_HINT = "create one in Shop Manager -- the API cannot"


class ShopCatalogError(UserFacingError, ValueError):
    """A name in config that does not resolve, or an omission that needed
    disambiguating. Always names every candidate the shop actually has, since
    guessing at a section, a shipping profile, a return policy or a
    production partner is exactly the mistake this exists to prevent."""


@dataclass(frozen=True)
class ReturnPolicyTerms:
    """A return policy's identity, since Etsy gives the resource no title
    (PRD 59). ``within_days`` of ``None`` matches any deadline -- only used
    internally; config always supplies all three."""

    accepts_returns: bool
    accepts_exchanges: bool
    within_days: int | None = None


class EtsyShopCatalog:
    """Sections, shipping profiles, return policies and production partners,
    fetched at most once each per instance."""

    def __init__(
        self, shop_client: EtsyShopClient, listing_client: EtsyListingClient, shop_id: int
    ) -> None:
        self._shop_client = shop_client
        self._listing_client = listing_client
        self._shop_id = shop_id
        self._sections: list[ShopSection] | None = None
        self._shipping_profiles: list[ShippingProfile] | None = None
        self._return_policies: list[ReturnPolicy] | None = None
        self._production_partners: list[ProductionPartner] | None = None

    # --------------------------------------------------------- the four reads

    def _all_sections(self) -> list[ShopSection]:
        if self._sections is None:
            self._sections = self._shop_client.shop_sections(self._shop_id)
        return self._sections

    def _all_shipping_profiles(self) -> list[ShippingProfile]:
        if self._shipping_profiles is None:
            # Deleted profiles stay in the list Etsy returns (measured); a
            # config naming one should get "no such profile", not a silent
            # match against something no longer offered.
            self._shipping_profiles = [
                profile
                for profile in self._listing_client.shipping_profiles(self._shop_id)
                if not profile.is_deleted
            ]
        return self._shipping_profiles

    def _all_return_policies(self) -> list[ReturnPolicy]:
        if self._return_policies is None:
            self._return_policies = self._shop_client.return_policies(self._shop_id)
        return self._return_policies

    def _all_production_partners(self) -> list[ProductionPartner]:
        if self._production_partners is None:
            self._production_partners = self._listing_client.production_partners(self._shop_id)
        return self._production_partners

    # -------------------------------------------------------------- section

    def shop_section(self, name: str) -> ShopSection:
        for section in self._all_sections():
            if section.title == name:
                return section
        raise ShopCatalogError(
            f"no shop section named {name!r}. {_options(s.title for s in self._all_sections())}"
        )

    # ------------------------------------------------------ shipping profile

    def shipping_profile(self, name: str) -> ShippingProfile:
        for profile in self._all_shipping_profiles():
            if profile.title == name:
                return profile
        raise ShopCatalogError(
            f"no shipping profile named {name!r}. "
            f"{_options(p.title for p in self._all_shipping_profiles())}"
        )

    # -------------------------------------------------------- return policy

    def return_policy(self, terms: ReturnPolicyTerms | None) -> ReturnPolicy:
        """The policy matching ``terms``, or -- omitted -- the shop's only
        one. Two or more with nothing named is an error, not a guess (PRD 59)."""
        policies = self._all_return_policies()
        if terms is None:
            if len(policies) == 1:
                return policies[0]
            raise ShopCatalogError(
                "no return_policy given, and the shop has more than one to choose "
                f"from. {_options((p.describe() for p in policies), empty=SHOP_MANAGER_HINT)}"
            )
        for policy in policies:
            if (
                policy.accepts_returns == terms.accepts_returns
                and policy.accepts_exchanges == terms.accepts_exchanges
                and (terms.within_days is None or policy.return_deadline == terms.within_days)
            ):
                return policy
        raise ShopCatalogError(
            "no return policy matches the terms given. "
            f"{_options((p.describe() for p in policies), empty=SHOP_MANAGER_HINT)}"
        )

    # --------------------------------------------------- production partner

    def production_partner(self, name: str | None) -> ProductionPartner:
        """The resolution ladder decision 3 sets out: named, then the shop's
        only one, then an error naming every candidate by name *and*
        location -- generic partner names make the location the
        distinguishing half."""
        partners = self._all_production_partners()
        if not partners:
            raise ShopCatalogError(
                "the shop has no production partners, and none can be created "
                f"through the API. {SHOP_MANAGER_HINT} before who_made: someone_else "
                "can be used."
            )
        if name is not None:
            wanted = normalise(name)
            for partner in partners:
                if partner.partner_name is not None and normalise(partner.partner_name) == wanted:
                    return partner
            raise ShopCatalogError(
                f"no production partner named {name!r}. {_options(_partner_labels(partners))}"
            )
        if len(partners) == 1:
            return partners[0]
        raise ShopCatalogError(
            "several production partners exist and none was named. Set "
            f"production_partner: to one of: {_options(_partner_labels(partners))}"
        )


def _partner_labels(partners: list[ProductionPartner]) -> list[str]:
    return [f"{p.partner_name} ({p.location})" for p in partners]


def _options(names: Iterable[str], *, empty: str = SHOP_MANAGER_HINT) -> str:
    """``Valid names: a, b`` -- or a hint naming the Shop Manager step when
    there is nothing to offer, since typing a name into config cannot create
    a section, profile, policy or partner the shop does not have."""
    listed = sorted(names)
    return f"Valid names: {', '.join(listed)}" if listed else empty
