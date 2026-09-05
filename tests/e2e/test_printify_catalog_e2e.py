"""The Printify catalog, against the real API. ``-m e2e``, skipped by default.

Everything below this layer talks to an ``httpx.MockTransport`` fed by payloads
typed into ``tests/contract/test_catalog_http.py``. Transcripts beat invented
fixtures -- that file records what an invented one cost: ``placeholders`` was
put at the top level, which Printify does not do, and every layer agreed with
the fiction while none agreed with the API, so a profile shipped with no print
area at all.

But a transcript is a photograph, and nothing re-takes it. If Printify moves a
field tomorrow, every offline test stays green and the failure surfaces as a
user's ``new`` run falling over. That is the gap this file closes: it asks the
real API the questions the offline suite answers from memory.

Read-only. Every call is a GET against ``/v1/catalog/*``, so this creates no
products and costs no state; re-run it freely. The write-side e2e tests that
do cost state arrive with Phase 2, against a throwaway shop.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from etsy_listings.catalog.http import BASE_URL, HttpCatalogClient
from etsy_listings.catalog.models import Blueprint, PrintProvider
from etsy_listings.catalog.resolve import CatalogResolutionError, resolve_blueprint

pytestmark = pytest.mark.e2e

GARMENT_BRAND = "Comfort Colors"
GARMENT_MODEL = "1717"
"""The blank this shop actually sells, identified the way anyone who buys
blanks identifies one -- by brand and model. Deliberately *not* by title:
Printify titles it "Unisex Garment-Dyed T-shirt", which half a dozen brands
share, and ``build_blueprint_choices`` already columns brand and model for
exactly that reason. Matching on brand avoids depending on the registered-trade-
mark sign Printify puts in it ("Comfort Colors®")."""


def _garment(blueprints: list[Blueprint]) -> Blueprint:
    match = next(
        (b for b in blueprints if b.brand.startswith(GARMENT_BRAND) and b.model == GARMENT_MODEL),
        None,
    )
    if match is None:
        pytest.fail(
            f"Printify no longer lists a {GARMENT_BRAND} {GARMENT_MODEL}. "
            f"If it was withdrawn, the profiles built on it need a new blueprint."
        )
    return match


@pytest.fixture(scope="session")
def garment(catalog: HttpCatalogClient) -> Blueprint:
    return _garment(catalog.blueprints())


@pytest.fixture(scope="session")
def provider(catalog: HttpCatalogClient, garment: Blueprint) -> PrintProvider:
    providers = catalog.print_providers(garment.id)
    assert providers, f"no print providers for blueprint {garment.id}"
    return providers[0]


@pytest.fixture(scope="session")
def variant_payload(
    catalog: HttpCatalogClient, garment: Blueprint, provider: PrintProvider
) -> dict[str, Any]:
    """The raw variants response. The *shape* is what several tests below are
    about, so they read the payload rather than the decoded model."""
    response = catalog._get(  # noqa: SLF001 - the wire shape is the thing under test
        f"/blueprints/{garment.id}/print_providers/{provider.id}/variants.json"
    )
    payload: dict[str, Any] = response.json()
    return payload


class TestTheCatalogAnswers:
    def test_blueprints_returns_a_decodable_non_empty_list(
        self, catalog: HttpCatalogClient
    ) -> None:
        blueprints = catalog.blueprints()
        assert blueprints, "Printify returned an empty catalog"
        assert all(isinstance(b, Blueprint) for b in blueprints)

    def test_the_shops_own_garment_is_still_listed(self, garment: Blueprint) -> None:
        assert garment.title
        assert garment.brand.startswith(GARMENT_BRAND)

    def test_print_providers_decode_for_it(self, provider: PrintProvider) -> None:
        assert isinstance(provider, PrintProvider)
        assert provider.title


class TestCatalogReadsNeedNoCredentials:
    """The catalog API is public, and the tool should not pretend otherwise.

    ``catalog/http.py`` is built on the opposite claim -- that every
    ``/v1/catalog/*.json`` call needs a token with the ``catalog.read`` scope
    and a token-less client gets "a bare 401". Against the live API today that
    is false: all four endpoints answer 200 with a junk token and with no
    ``Authorization`` header at all.

    These tests assert the behaviour that is actually there. If they start
    failing, Printify has made the catalog private, ``CatalogAuthError``'s
    branch is live again, and ``new`` genuinely does need a token before it
    can prompt for anything.
    """

    ENDPOINTS = [
        "/blueprints.json",
        "/blueprints/706/print_providers.json",
        "/blueprints/706/print_providers/29/variants.json",
        "/blueprints/706/print_providers/29/shipping.json",
    ]

    # These need no credential to *prove their point* -- that is the point --
    # but they still take `printify_token` so they skip with the rest of the
    # layer. The gate is "is this machine set up to talk to the live API at
    # all", not "does this particular request need a token"; an e2e run on an
    # unconfigured machine should reach the network exactly nowhere.

    @pytest.mark.parametrize("path", ENDPOINTS)
    def test_an_invalid_token_is_still_served(self, printify_token: str, path: str) -> None:
        response = httpx.get(
            BASE_URL + path, headers={"Authorization": "Bearer not-a-real-token"}, timeout=30.0
        )
        assert response.status_code == 200

    @pytest.mark.parametrize("path", ENDPOINTS)
    def test_no_authorization_header_at_all_is_still_served(
        self, printify_token: str, path: str
    ) -> None:
        response = httpx.get(BASE_URL + path, timeout=30.0)
        assert response.status_code == 200

    def test_the_client_works_with_a_junk_token(self, printify_token: str) -> None:
        """The practical consequence: nothing in Phase 0/1 needs a credential.
        Demanding one is friction, not security."""
        assert HttpCatalogClient("not-a-real-token").blueprints()


class TestVariantsMatchWhatTheCodeAssumes:
    """Assumptions ``HttpCatalogClient.variants`` and ``build_profile`` rest on.
    Each, if wrong, yields a plausible-looking profile that fails much later --
    which is what happened the last time one of them was wrong."""

    def test_placeholders_are_nested_inside_each_variant(
        self, variant_payload: dict[str, Any]
    ) -> None:
        """The bug that motivated the contract layer in the first place."""
        assert "placeholders" not in variant_payload, (
            "Printify now returns a top-level `placeholders`; "
            "HttpCatalogClient.variants reads it per-variant"
        )
        assert "placeholders" in variant_payload["variants"][0]

    def test_options_still_carry_colour_and_size(self, variant_payload: dict[str, Any]) -> None:
        """``VariantOptions`` requires both, and ``build_profile`` derives the
        size list and the whole colour set from them."""
        options = variant_payload["variants"][0]["options"]
        assert "color" in options
        assert "size" in options

    def test_a_placeholder_carries_a_position_and_pixel_dimensions(
        self, variant_payload: dict[str, Any]
    ) -> None:
        placeholder = variant_payload["variants"][0]["placeholders"][0]
        assert "position" in placeholder
        assert isinstance(placeholder["width"], int)
        assert isinstance(placeholder["height"], int)

    def test_the_front_placeholder_exists_and_decodes(
        self, catalog: HttpCatalogClient, garment: Blueprint, provider: PrintProvider
    ) -> None:
        """``new`` writes ``placeholder: front`` into every profile it creates."""
        variant_set = catalog.variants(garment.id, provider.id)
        assert variant_set.variants, "no variants decoded"

        area = variant_set.placeholder("front")
        assert area is not None, (
            f"no 'front' print area; positions offered are {variant_set.positions()}"
        )
        assert area.width > 0
        assert area.height > 0

    def test_colours_and_sizes_are_non_empty(
        self, catalog: HttpCatalogClient, garment: Blueprint, provider: PrintProvider
    ) -> None:
        variant_set = catalog.variants(garment.id, provider.id)
        assert variant_set.colors, "no colours -- `new` would write an empty listing"
        assert {v.options.size for v in variant_set.variants}

    def test_shipping_decodes(
        self, catalog: HttpCatalogClient, garment: Blueprint, provider: PrintProvider
    ) -> None:
        """Phase 2 prices against these; decoding them is worth knowing now."""
        assert catalog.shipping(garment.id, provider.id).profiles


class TestTheOfflineTranscriptsStillMatchReality:
    """The offline suite trusts payload shapes typed into the contract test.
    These compare those keys against a live response, so a field Printify
    *adds* is ignored -- as it should be -- while one it *removes* fails."""

    def test_blueprint_keys_the_transcript_claims_still_exist(
        self, catalog: HttpCatalogClient, contract_fixtures: dict[str, Any]
    ) -> None:
        transcribed = set(contract_fixtures["blueprints"][0])
        live = catalog._get("/blueprints.json").json()[0]  # noqa: SLF001
        assert transcribed <= set(live), (
            f"the transcript claims blueprint keys Printify no longer returns: "
            f"{sorted(transcribed - set(live))}"
        )

    def test_provider_keys_the_transcript_claims_still_exist(
        self,
        catalog: HttpCatalogClient,
        garment: Blueprint,
        contract_fixtures: dict[str, Any],
    ) -> None:
        transcribed = set(contract_fixtures["providers"][0])
        live = catalog._get(  # noqa: SLF001
            f"/blueprints/{garment.id}/print_providers.json"
        ).json()[0]
        assert transcribed <= set(live), (
            f"the transcript claims provider keys Printify no longer returns: "
            f"{sorted(transcribed - set(live))}"
        )

    def test_variant_keys_the_transcript_claims_still_exist(
        self, variant_payload: dict[str, Any], contract_fixtures: dict[str, Any]
    ) -> None:
        transcribed = set(contract_fixtures["variants"]["variants"][0])
        live = variant_payload["variants"][0]
        assert transcribed <= set(live), (
            f"the transcript claims variant keys Printify no longer returns: "
            f"{sorted(transcribed - set(live))}"
        )


class TestTheDocumentedExampleProfileResolves:
    """``Profile.blueprint`` is a *title*, resolved against the live catalog by
    ``resolve_blueprint``. So every blueprint title this repo puts in front of
    a user -- the PRD's example config, the getting-started guide, the fixture
    workspace -- has to be one Printify actually returns.
    """

    def test_the_title_the_docs_tell_users_to_write_resolves(
        self, catalog: HttpCatalogClient
    ) -> None:
        """Currently FAILS, and correctly so.

        docs/prd.md, docs/getting-started.md and the fixture profile all say
        ``blueprint: Comfort Colors 1717``. Printify has no blueprint with
        that title: 706 is titled "Unisex Garment-Dyed T-shirt", with the
        brand "Comfort Colors®" and the model "1717". A user following the
        guide writes a profile that can never resolve.
        """
        resolve_blueprint("Comfort Colors 1717", catalog.blueprints())

    def test_the_real_title_resolves(self, catalog: HttpCatalogClient, garment: Blueprint) -> None:
        """The same call with the title Printify actually returns, so the
        failure above is pinned to the *value* in the docs and not to
        ``resolve_blueprint`` being broken."""
        assert resolve_blueprint(garment.title, catalog.blueprints()).id == garment.id

    def test_resolution_failure_names_the_near_misses(self, catalog: HttpCatalogClient) -> None:
        with pytest.raises(CatalogResolutionError) as caught:
            resolve_blueprint("Comfort Colors 1717", catalog.blueprints())
        assert "Comfort Colors 1717" in str(caught.value)
