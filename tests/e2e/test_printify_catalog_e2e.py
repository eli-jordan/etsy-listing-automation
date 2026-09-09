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

from etsy_listings.clients.printify import BASE_URL, HttpCatalogClient
from etsy_listings.clients.printify.models import Blueprint, PrintProvider
from etsy_listings.clients.printify.resolve import CatalogResolutionError, resolve_blueprint

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


class TestWhatTheCatalogActuallyRequires:
    """What the catalog checks, measured rather than assumed.

    ``clients/printify/catalog.py`` and docs/setup.md say every ``/v1/catalog/*.json`` call
    needs a personal access token with the ``catalog.read`` scope. Two of them
    plainly do not: ``blueprints`` and ``print_providers`` are served with no
    ``Authorization`` header at all. That matters for how hard ``new`` should
    push a user to get a token before it will run, so it is measured here
    rather than believed.

    What this class deliberately no longer asserts is how the API treats a
    *bad* token. It used to serve the per-provider endpoints to any header at
    all, junk included, and tests pinned that down; Printify now 401s some of
    them and not others, differing between machines in a way that looks like a
    rollout mid-flight. Nothing here depends on the answer -- a valid token
    works, and ``PrintifyAuthError`` already turns a 401 into a named failure
    (see the contract layer) -- so those assertions were dropped rather than
    re-pinned to a moving target.

    This takes ``printify_token`` despite not needing one, so it skips with the
    rest of the layer: an e2e run on an unconfigured machine should reach the
    network exactly nowhere.
    """

    PUBLIC = [
        "/v1/catalog/blueprints.json",
        "/v1/catalog/blueprints/706/print_providers.json",
    ]

    @pytest.mark.parametrize("path", PUBLIC)
    def test_the_listing_endpoints_need_no_header_at_all(
        self, printify_token: str, path: str
    ) -> None:
        assert httpx.get(BASE_URL + path, timeout=30.0).status_code == 200


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
    """Every blueprint this repo puts in front of a user -- the PRD's example
    profile, the getting-started guide, the fixture workspace -- has to be one
    Printify actually returns.

    This is where that gets checked against the catalog rather than against a
    fixture agreeing with itself. It is what caught the previous value: a bare
    ``blueprint: Comfort Colors 1717``, a title Printify has never used, which
    made every profile written by following the guide unresolvable (PRD 23,
    since revised to brand + model).
    """

    DOCUMENTED_BRAND = "Comfort Colors"
    DOCUMENTED_MODEL = "1717"

    def test_the_brand_and_model_the_docs_tell_users_to_write_resolve(
        self, catalog: HttpCatalogClient, garment: Blueprint
    ) -> None:
        resolved = resolve_blueprint(
            self.DOCUMENTED_BRAND, self.DOCUMENTED_MODEL, catalog.blueprints()
        )
        assert resolved.id == garment.id

    def test_it_resolves_without_the_trademark_sign_the_catalog_carries(
        self, catalog: HttpCatalogClient
    ) -> None:
        """The catalog's brand is "Comfort Colors®". The docs tell users to
        write "Comfort Colors", and that has to be enough."""
        assert "®" not in self.DOCUMENTED_BRAND
        assert resolve_blueprint(self.DOCUMENTED_BRAND, self.DOCUMENTED_MODEL, catalog.blueprints())

    def test_the_recorded_title_is_still_what_printify_calls_it(self, garment: Blueprint) -> None:
        """``title`` takes no part in matching, so a drift here is not a broken
        profile -- but the docs and fixture quote it, and prose that has gone
        stale is worth knowing about."""
        assert garment.title == "Unisex Garment-Dyed T-shirt"

    def test_an_unknown_garment_lists_brand_model_pairs_to_choose_from(
        self, catalog: HttpCatalogClient
    ) -> None:
        with pytest.raises(CatalogResolutionError) as caught:
            resolve_blueprint("Not A Real Brand", "0000", catalog.blueprints())
        message = str(caught.value)
        assert "Not A Real Brand 0000" in message
        # Pairs, not titles: what it lists must be pasteable into a profile.
        assert f"{self.DOCUMENTED_BRAND}® {self.DOCUMENTED_MODEL}" in message
