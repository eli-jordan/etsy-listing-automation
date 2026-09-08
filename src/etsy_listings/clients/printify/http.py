"""Real HTTP implementation of :class:`PrintifyClient` against the shop-scoped
Printify endpoints.

Separate from ``catalog/http.py`` on purpose: that client is pinned to
``/v1/catalog`` and reads only, and the whole value of the split is that
nothing holding a ``CatalogClient`` can reach a call that creates a product.
The token and the host are the same; the authority they carry is not.

Error decoding leans on a shape this API keeps to without exception -- every
failure observed against the live API is

    {"status": "error", "code": 8251, "message": "Validation failed.",
     "errors": {"reason": "...", "code": 8251}}

``errors.reason`` is a human sentence naming the offending field, and is the
only part of that envelope worth putting in front of a user
(docs/api-findings.md).
"""

from __future__ import annotations

import base64
import time
from collections.abc import Callable
from typing import Any

import httpx

from etsy_listings.clients.printify.models import (
    PrintAreaSpec,
    Product,
    ProductSpec,
    Shop,
    Upload,
)
from etsy_listings.clients.printify.protocol import PrintifyClient
from etsy_listings.clients.retry import DEFAULT_POLICY, RetryPolicy, with_retries
from etsy_listings.config.secrets import PRINTIFY_TOKEN_VAR

BASE_URL = "https://api.printify.com"
"""No ``/v1`` suffix, unlike the catalog client's: this client addresses
several path families (``/v1/shops``, ``/v1/uploads``) and spelling the
version once per path keeps each call site readable as the documented
endpoint it is."""

TokenSource = str | Callable[[], str]
"""A token, or something that produces one on demand. Resolved lazily for the
same reason the catalog client does it: ``plan`` builds clients it may never
call, and demanding a credential at construction would fail every workspace
that has not reached the phase which needs one."""

HTTP_NOT_FOUND = 404
PRODUCTS_PAGE_SIZE = 50

DEFAULT_TIMEOUT_SECONDS = 120.0
"""Generous, because uploads travel this client: a print file is megabytes,
and the default 5s timeout turns a slow link into an inscrutable failure."""


class PrintifyAuthError(RuntimeError):
    """Printify rejected the credentials. Distinct from every other failure,
    because the fix is a specific human action rather than a retry."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(
            f"Printify rejected the request ({status_code}).\n"
            f"  Check {PRINTIFY_TOKEN_VAR} in your workspace's .env -- if the token is "
            f"present, it is expired, revoked, or missing a scope.\n"
            f"  Writing products needs more than `catalog.read`: the token must also "
            f"carry the shop and product scopes.\n"
            f"  Regenerate it at printify.com/app/account/connections, or re-run "
            f"`etsy-listings setup`, which verifies a token before storing it."
        )


class PrintifyApiError(RuntimeError):
    """A request Printify understood and refused.

    Carries ``code`` because Printify's numeric codes are stable enough to
    branch on (8254 is "shop not connected to a sales channel", which
    ``publish`` will want to recognise), and renders ``errors.reason`` because
    that is the part a human can act on.
    """

    def __init__(self, status_code: int, *, code: int | None, reason: str) -> None:
        self.status_code = status_code
        self.code = code
        self.reason = reason
        detail = f" (code {code})" if code is not None else ""
        super().__init__(f"Printify refused the request with {status_code}{detail}: {reason}")


def _decode_error(response: httpx.Response) -> PrintifyApiError:
    """Pull ``errors.reason`` out of the envelope, tolerating its absence.

    A 502 from a proxy is HTML, not JSON. Crashing while decoding the thing
    that explains the failure is the worst possible time to crash, so every
    step here degrades rather than raising.
    """
    reason = response.text.strip() or "no response body"
    code: int | None = None
    try:
        body: Any = response.json()
    except ValueError:
        return PrintifyApiError(response.status_code, code=None, reason=reason)

    if isinstance(body, dict):
        errors = body.get("errors")
        if isinstance(errors, dict) and isinstance(errors.get("reason"), str):
            reason = errors["reason"]
        elif isinstance(body.get("message"), str):
            reason = body["message"]
        if isinstance(body.get("code"), int):
            code = body["code"]
    return PrintifyApiError(response.status_code, code=code, reason=reason)


class HttpPrintifyClient(PrintifyClient):
    def __init__(
        self,
        token: TokenSource,
        *,
        client: httpx.Client | None = None,
        policy: RetryPolicy = DEFAULT_POLICY,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._token = token
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=DEFAULT_TIMEOUT_SECONDS)
        self._policy = policy
        self._sleep = sleep

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        token = self._token if isinstance(self._token, str) else self._token()

        def send() -> httpx.Response:
            return self._client.request(
                method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs
            )

        # Retries happen *before* the error decoding below, so a 429 that
        # clears on the second attempt never becomes an exception at all --
        # and one that does not clear surfaces as the real decoded error
        # rather than a retry wrapper's summary of it (A21).
        response = with_retries(send, method, self._policy, sleep=self._sleep)

        if response.status_code in (401, 403):
            raise PrintifyAuthError(response.status_code)
        if response.is_error:
            raise _decode_error(response)
        return response

    def shops(self) -> list[Shop]:
        response = self._request("GET", "/v1/shops.json")
        return [Shop.model_validate(item) for item in response.json()]

    # ------------------------------------------------------------- uploads

    def upload_image(self, file_name: str, contents: bytes) -> Upload:
        response = self._request(
            "POST",
            "/v1/uploads/images.json",
            json={
                "file_name": file_name,
                "contents": base64.b64encode(contents).decode("ascii"),
            },
        )
        return Upload.model_validate(response.json())

    # ------------------------------------------------------------ products

    def get_product(self, shop_id: int, product_id: str) -> Product | None:
        """The product, or ``None`` if it is gone.

        Deleted in Printify's web app between runs is an ordinary thing to
        happen, and it means "create one", not "crash".
        """
        try:
            response = self._request("GET", f"/v1/shops/{shop_id}/products/{product_id}.json")
        except PrintifyApiError as exc:
            if exc.status_code == HTTP_NOT_FOUND:
                return None
            raise
        return Product.model_validate(response.json())

    def create_product(self, shop_id: int, spec: ProductSpec) -> Product:
        """Create, hidden.

        ``visible: false`` because a product nobody has reviewed has no
        business being visible, and the field *is* writable despite the API
        reference marking it read-only (docs/api-findings.md).
        """
        body = {
            "title": spec.title,
            "description": spec.description,
            "blueprint_id": spec.blueprint_id,
            "print_provider_id": spec.print_provider_id,
            # On create the print areas cover only the variants being created.
            # On update they must cover every variant the product has -- see
            # `update_product`.
            "variants": _variant_bodies(spec.variants, retiring={}),
            "print_areas": _print_area_bodies(spec.print_areas),
            "visible": False,
        }
        response = self._request("POST", f"/v1/shops/{shop_id}/products.json", json=body)
        return Product.model_validate(response.json())

    def update_product(
        self, shop_id: int, product_id: str, spec: ProductSpec, *, live: Product
    ) -> Product:
        """Update, taking ``live`` because an update cannot be built without it.

        Two measured rules make this differ from create rather than share it:

        - **``variants`` merges by id.** Omitting one does not disable it, so a
          colour the listing dropped has to be named with an explicit
          ``is_enabled: false`` -- and carry a price, because a variant entry
          is never partial.
        - **``print_areas.variant_ids`` must cover every variant the product
          has**, not the ones being changed. The payload that created the
          product is rejected as an update of it (400 code 8251).
        """
        retiring = {
            variant.id: variant.price
            for variant in live.variants
            if variant.is_enabled and variant.id not in spec.variants
        }
        body = {
            "title": spec.title,
            "description": spec.description,
            "variants": _variant_bodies(spec.variants, retiring=retiring),
            "print_areas": _print_area_bodies(spec.print_areas, cover=live.all_variant_ids()),
        }
        response = self._request(
            "PUT", f"/v1/shops/{shop_id}/products/{product_id}.json", json=body
        )
        return Product.model_validate(response.json())

    def delete_product(self, shop_id: int, product_id: str) -> None:
        self._request("DELETE", f"/v1/shops/{shop_id}/products/{product_id}.json")

    def find_product_by_copy(self, shop_id: int, *, title: str, description: str) -> str | None:
        """The id of a product already carrying this copy, or ``None``. PRD 48.

        A walk, not a query: ``GET products.json`` accepts ``title``,
        ``search`` and ``sku`` and ignores all three, so the match is
        client-side over every page. Affordable because it runs only where a
        create is already pending -- never on a no-op ``plan``.

        Deleted products stay in the listing, and adopting one would bind the
        lockfile to a product that can no longer be updated.
        """
        page = 1
        while True:
            response = self._request(
                "GET",
                f"/v1/shops/{shop_id}/products.json",
                params={"page": page, "limit": PRODUCTS_PAGE_SIZE},
            )
            body = response.json()
            for raw in body.get("data", []):
                if raw.get("is_deleted"):
                    continue
                if raw.get("title") == title and raw.get("description") == description:
                    return str(raw["id"])
            if page >= int(body.get("last_page", page)):
                return None
            page += 1


def _variant_bodies(variants: dict[int, int], *, retiring: dict[int, int]) -> list[dict[str, Any]]:
    """Enabled variants, plus explicit disables for the ones being retired.

    **Every entry carries a price, including a disabled one.** Measured:
    ``{"id": ..., "is_enabled": false}`` alone is
    ``400 8150 "variants.0.price: The variants.0.price field is required."``
    A variant entry is never partial, which is also why the lockfile has to
    remember what each enabled variant cost -- the desired document cannot
    supply a price for a colour it no longer offers.
    """
    bodies = [
        {"id": variant_id, "price": price, "is_enabled": True}
        for variant_id, price in variants.items()
    ]
    bodies.extend(
        {"id": variant_id, "price": price, "is_enabled": False}
        for variant_id, price in retiring.items()
    )
    return bodies


def _print_area_bodies(
    areas: tuple[PrintAreaSpec, ...], *, cover: tuple[int, ...] | None = None
) -> list[dict[str, Any]]:
    """Print areas as Printify wants them, optionally widened to ``cover``.

    ``cover`` is the update coverage rule: the union across all entries must
    name every variant the product has. Widening the **last** area rather than
    spreading the extras keeps every earlier area's variant set exactly as the
    caller partitioned it, which is what PRD 30's on-light/on-dark split
    depends on -- a dark-ink group that quietly gained the whole matrix would
    print the wrong file on half the shirts.
    """
    bodies: list[dict[str, Any]] = [
        {
            "variant_ids": list(area.variant_ids),
            "placeholders": [
                {
                    "position": placeholder.position,
                    "images": [image.model_dump() for image in placeholder.images],
                }
                for placeholder in area.placeholders
            ],
        }
        for area in areas
    ]
    if cover is not None and bodies:
        named = {vid for body in bodies for vid in body["variant_ids"]}
        bodies[-1]["variant_ids"] = sorted(set(bodies[-1]["variant_ids"]) | (set(cover) - named))
    return bodies
