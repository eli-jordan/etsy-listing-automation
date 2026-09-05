"""Real HTTP implementation of :class:`CatalogClient` against Printify's
catalog endpoints. Exercised by the contract layer through ``httpx``'s mock
transport (payload shape, auth headers, error decoding); the env-gated ``-m
e2e`` layer is what ever touches the real API.

**These endpoints are authenticated.** They were documented here as "public,
unauthenticated" and they are not: every ``/v1/catalog/*.json`` call needs a
personal access token with the ``catalog.read`` scope, and without one
Printify answers ``401 Unauthorized``. That mistake is why ``new`` died on a
raw httpx traceback.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from etsy_listings.catalog.client import CatalogClient
from etsy_listings.catalog.models import (
    Blueprint,
    PrintAreaPlaceholder,
    PrintProvider,
    ShippingCost,
    ShippingProfile,
    ShippingRates,
    Variant,
    VariantOptions,
    VariantSet,
)
from etsy_listings.config.secrets import PRINTIFY_TOKEN_VAR

BASE_URL = "https://api.printify.com/v1/catalog"

TokenSource = str | Callable[[], str]
"""A token, or something that produces one on demand. ``plan``/``apply`` build
a catalog client eagerly even though no Phase 0/1 stage calls it -- resolving
the token at construction time would make every ``plan`` fail in a workspace
that has no ``.env`` yet, and a cached catalog read needs no token at all."""


class CatalogAuthError(RuntimeError):
    """Printify rejected the credentials. Distinct from a transport or server
    error, because the fix is a specific human action, not a retry."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(
            f"Printify rejected the catalog request ({status_code}).\n"
            f"  The catalog API is not public: it needs a personal access token with "
            f"the `catalog.read` scope.\n"
            f"  Check {PRINTIFY_TOKEN_VAR} in your workspace's .env -- if the token is "
            f"present, it is expired, revoked, or missing that scope.\n"
            f"  Regenerate it at printify.com/app/account/connections (docs/setup.md "
            f"section 1.3)."
        )


class HttpCatalogClient(CatalogClient):
    def __init__(self, token: TokenSource, *, client: httpx.Client | None = None) -> None:
        self._token = token
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=30.0)

    def _get(self, path: str) -> httpx.Response:
        token = self._token if isinstance(self._token, str) else self._token()
        response = self._client.get(path, headers={"Authorization": f"Bearer {token}"})
        if response.status_code in (401, 403):
            raise CatalogAuthError(response.status_code)
        response.raise_for_status()
        return response

    def blueprints(self) -> list[Blueprint]:
        response = self._get("/blueprints.json")
        return [Blueprint.model_validate(item) for item in response.json()]

    def print_providers(self, blueprint_id: int) -> list[PrintProvider]:
        response = self._get(f"/blueprints/{blueprint_id}/print_providers.json")
        return [PrintProvider.model_validate(item) for item in response.json()]

    def variants(self, blueprint_id: int, provider_id: int) -> VariantSet:
        response = self._get(
            f"/blueprints/{blueprint_id}/print_providers/{provider_id}/variants.json"
        )
        payload = response.json()
        # `placeholders` is nested inside each variant -- the response has no
        # top-level one, and reading it as though it did silently produced a
        # set with no print areas at all. See `Variant.placeholders`.
        variants = tuple(
            Variant(
                id=item["id"],
                title=item["title"],
                options=VariantOptions.model_validate(item["options"]),
                placeholders=tuple(
                    PrintAreaPlaceholder.model_validate(p) for p in item.get("placeholders", [])
                ),
            )
            for item in payload["variants"]
        )
        return VariantSet(variants=variants)

    def shipping(self, blueprint_id: int, provider_id: int) -> ShippingRates:
        response = self._get(
            f"/blueprints/{blueprint_id}/print_providers/{provider_id}/shipping.json"
        )
        payload = response.json()
        profiles = tuple(
            ShippingProfile(
                variant_ids=tuple(item["variant_ids"]),
                first_item=ShippingCost.model_validate(item["first_item"]),
                additional_items=ShippingCost.model_validate(item["additional_items"]),
            )
            for item in payload.get("profiles", [])
        )
        return ShippingRates(profiles=profiles)
