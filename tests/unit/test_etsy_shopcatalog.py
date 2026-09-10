"""Name -> id resolution for the fields `shop.yaml`/`listing.yaml` refer to by
name (decision 2, PRD 53/54/59): a shop section, a shipping profile, a return
policy addressed by its terms, and the production partner ladder (decision 3).

Pure resolution logic over lists the fakes hand back, so this is the unit
layer -- no workspace, no transport -- per phase-3-etsy.md's "Testing" table:
"name normalisation and resolution failure messages".
"""

from __future__ import annotations

import pytest

from etsy_listings.clients.etsy.fakes import FakeEtsyListingClient
from etsy_listings.clients.etsy.models import (
    ProductionPartner,
    ReturnPolicy,
    ShippingProfile,
    ShopSection,
)
from etsy_listings.clients.etsy.shopcatalog import (
    EtsyShopCatalog,
    ReturnPolicyTerms,
    ShopCatalogError,
)

SHOP_ID = 67961328


def _catalog(
    *,
    sections: list[ShopSection] | None = None,
    policies: list[ReturnPolicy] | None = None,
    shipping_profiles: list[ShippingProfile] | None = None,
    production_partners: list[ProductionPartner] | None = None,
) -> tuple[EtsyShopCatalog, FakeEtsyListingClient]:
    client = FakeEtsyListingClient(
        sections=sections,
        policies=policies,
        shipping_profiles=shipping_profiles,
        production_partners=production_partners,
    )
    return EtsyShopCatalog(client, SHOP_ID), client


# ------------------------------------------------------------------ sections


def test_a_section_resolves_by_its_title() -> None:
    catalog, _ = _catalog(
        sections=[
            ShopSection(shop_section_id=44, title="Tees"),
            ShopSection(shop_section_id=45, title="Hoodies"),
        ]
    )

    assert catalog.shop_section("Hoodies").shop_section_id == 45


def test_an_unknown_section_lists_the_shops_actual_sections() -> None:
    catalog, _ = _catalog(sections=[ShopSection(shop_section_id=44, title="Tees")])

    with pytest.raises(ShopCatalogError, match="Tees"):
        catalog.shop_section("Retro Tees")


def test_no_sections_at_all_names_the_shop_manager_step() -> None:
    catalog, _ = _catalog(sections=[])

    with pytest.raises(ShopCatalogError, match="Shop Manager"):
        catalog.shop_section("Retro Tees")


# --------------------------------------------------------- shipping profiles


def test_a_shipping_profile_resolves_by_its_title() -> None:
    catalog, _ = _catalog(
        shipping_profiles=[ShippingProfile(shipping_profile_id=1, title="NOK standard tee")]
    )

    assert catalog.shipping_profile("NOK standard tee").shipping_profile_id == 1


def test_a_deleted_shipping_profile_is_not_offered() -> None:
    catalog, _ = _catalog(
        shipping_profiles=[
            ShippingProfile(shipping_profile_id=1, title="Old profile", is_deleted=True)
        ]
    )

    with pytest.raises(ShopCatalogError, match="Shop Manager"):
        catalog.shipping_profile("Old profile")


def test_an_unknown_shipping_profile_lists_the_shops_actual_ones() -> None:
    catalog, _ = _catalog(
        shipping_profiles=[ShippingProfile(shipping_profile_id=1, title="NOK standard tee")]
    )

    with pytest.raises(ShopCatalogError, match="NOK standard tee"):
        catalog.shipping_profile("NOK heavy tee")


# ----------------------------------------------------------- return policies


def test_a_shop_with_exactly_one_policy_needs_no_reference() -> None:
    catalog, _ = _catalog(
        policies=[
            ReturnPolicy(
                return_policy_id=1, accepts_returns=True, accepts_exchanges=True, return_deadline=30
            )
        ]
    )

    assert catalog.return_policy(None).return_policy_id == 1


def test_omitting_it_with_more_than_one_policy_lists_them_by_terms() -> None:
    catalog, _ = _catalog(
        policies=[
            ReturnPolicy(
                return_policy_id=1, accepts_returns=True, accepts_exchanges=True, return_deadline=30
            ),
            ReturnPolicy(return_policy_id=2, accepts_returns=False, accepts_exchanges=False),
        ]
    )

    with pytest.raises(ShopCatalogError, match="returns and exchanges within 30 days"):
        catalog.return_policy(None)


def test_terms_resolve_to_the_matching_policy() -> None:
    catalog, _ = _catalog(
        policies=[
            ReturnPolicy(
                return_policy_id=1, accepts_returns=True, accepts_exchanges=True, return_deadline=30
            ),
            ReturnPolicy(return_policy_id=2, accepts_returns=False, accepts_exchanges=False),
        ]
    )

    resolved = catalog.return_policy(
        ReturnPolicyTerms(accepts_returns=True, accepts_exchanges=True, within_days=30)
    )

    assert resolved.return_policy_id == 1


def test_terms_matching_nothing_list_what_the_shop_actually_has() -> None:
    catalog, _ = _catalog(
        policies=[
            ReturnPolicy(
                return_policy_id=1, accepts_returns=True, accepts_exchanges=True, return_deadline=30
            )
        ]
    )

    with pytest.raises(ShopCatalogError, match="returns and exchanges within 30 days"):
        catalog.return_policy(
            ReturnPolicyTerms(accepts_returns=True, accepts_exchanges=False, within_days=14)
        )


# ----------------------------------------------------------- production partner


def test_a_named_partner_resolves_through_the_same_normalisation_as_the_catalog() -> None:
    """PRD 23's blueprint: trademark signs and case fold away. Etsy renders
    partner names plainly, but the config author should not have to match its
    capitalisation exactly either."""
    catalog, _ = _catalog(
        production_partners=[
            ProductionPartner(production_partner_id=1, partner_name="The Print Provider")
        ]
    )

    assert catalog.production_partner("the print provider").production_partner_id == 1


def test_omitted_with_exactly_one_partner_uses_it() -> None:
    catalog, _ = _catalog(
        production_partners=[
            ProductionPartner(production_partner_id=1, partner_name="The Print Provider")
        ]
    )

    assert catalog.production_partner(None).production_partner_id == 1


def test_omitted_with_several_partners_names_them_by_name_and_location() -> None:
    """Generic partner names make the location the distinguishing half."""
    catalog, _ = _catalog(
        production_partners=[
            ProductionPartner(
                production_partner_id=1, partner_name="The Print Provider", location="Miami, FL"
            ),
            ProductionPartner(
                production_partner_id=2, partner_name="The Print Provider", location="Reno, NV"
            ),
        ]
    )

    with pytest.raises(ShopCatalogError, match="Miami, FL") as caught:
        catalog.production_partner(None)
    assert "Reno, NV" in str(caught.value)


def test_a_shop_with_no_partner_at_all_names_the_shop_manager_step() -> None:
    """The API is read-only for this resource -- there is no
    createShopProductionPartner -- so the message has to send a human to
    Shop Manager rather than suggest a name to type."""
    catalog, _ = _catalog(production_partners=[])

    with pytest.raises(ShopCatalogError, match="Shop Manager"):
        catalog.production_partner(None)


def test_an_unresolvable_named_partner_lists_the_shops_actual_ones() -> None:
    catalog, _ = _catalog(
        production_partners=[
            ProductionPartner(production_partner_id=1, partner_name="The Print Provider")
        ]
    )

    with pytest.raises(ShopCatalogError, match="The Print Provider"):
        catalog.production_partner("Some Other Partner")


# --------------------------------------------------------- once per run (A25)


def test_each_list_is_fetched_at_most_once_per_catalog() -> None:
    catalog, client = _catalog(
        sections=[ShopSection(shop_section_id=44, title="Tees")],
        shipping_profiles=[ShippingProfile(shipping_profile_id=1, title="NOK standard tee")],
    )

    catalog.shop_section("Tees")
    catalog.shop_section("Tees")
    catalog.shipping_profile("NOK standard tee")
    catalog.shipping_profile("NOK standard tee")

    assert client.section_calls == 1
    assert client.shipping_profile_calls == 1
