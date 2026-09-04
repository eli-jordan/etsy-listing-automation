"""Contract layer for the Printify catalog client: payload shape, auth, and
error decoding, driven through real ``httpx`` with a mock transport standing
in for the network (A4's "cassette" job -- a fake would tell us nothing about
the wire format or the headers that actually go out).

The reason this file exists: Printify's catalog endpoints are *not*
unauthenticated, contrary to what ``catalog/http.py`` used to claim. Every
``/v1/catalog/*.json`` call needs a personal access token with the
``catalog.read`` scope, so a token-less client gets a bare 401 and ``new``
falls over before it can prompt for anything.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from etsy_listings.catalog.http import BASE_URL, CatalogAuthError, HttpCatalogClient
from etsy_listings.config.secrets import MissingCredentialError, Secrets

BLUEPRINTS_PAYLOAD = [
    {"id": 6, "title": "Comfort Colors 1717", "brand": "Comfort Colors", "model": "1717"},
]
PROVIDERS_PAYLOAD = [{"id": 29, "title": "Monster Digital"}]
VARIANTS_PAYLOAD = {
    # Transcribed from a real response (blueprint 706 / provider 29), not
    # invented. The previous fixture put `placeholders` at the top level,
    # which Printify does not, and that fiction is precisely what let a
    # profile ship with no print area at all: every layer above agreed with
    # the fixture and none of them agreed with the API. A contract fixture
    # that is not a transcript is worse than no contract test.
    "id": 706,
    "title": "Unisex Garment-Dyed T-shirt",
    "variants": [
        {
            "id": 1,
            "title": "Black / S",
            "options": {"color": "Black", "size": "S"},
            "placeholders": [
                {"position": "front", "decoration_method": "dtg", "width": 3461, "height": 3955},
                {"position": "back", "decoration_method": "dtg", "width": 3461, "height": 3955},
            ],
            "decoration_methods": ["dtg"],
        },
        {
            "id": 2,
            "title": "Black / 3XL",
            "options": {"color": "Black", "size": "3XL"},
            "placeholders": [
                {"position": "front", "decoration_method": "dtg", "width": 4200, "height": 4800},
                {"position": "back", "decoration_method": "dtg", "width": 4200, "height": 4800},
            ],
            "decoration_methods": ["dtg"],
        },
    ],
}


def _client(handler, token: str = "test-token") -> HttpCatalogClient:
    transport = httpx.MockTransport(handler)
    return HttpCatalogClient(token, client=httpx.Client(transport=transport, base_url=BASE_URL))


def test_every_catalog_request_carries_the_bearer_token() -> None:
    """The bug: no Authorization header at all, so Printify answers 401."""
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.headers.get("authorization")))
        if request.url.path.endswith("/blueprints.json"):
            return httpx.Response(200, json=BLUEPRINTS_PAYLOAD)
        if request.url.path.endswith("/print_providers.json"):
            return httpx.Response(200, json=PROVIDERS_PAYLOAD)
        return httpx.Response(200, json=VARIANTS_PAYLOAD)

    client = _client(handler)
    client.blueprints()
    client.print_providers(6)
    client.variants(6, 29)

    assert [auth for _, auth in seen] == ["Bearer test-token"] * 3


def test_blueprints_decodes_the_documented_payload_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=BLUEPRINTS_PAYLOAD)

    blueprints = _client(handler).blueprints()
    assert [b.title for b in blueprints] == ["Comfort Colors 1717"]


def test_variants_decodes_variants_and_placeholders() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=VARIANTS_PAYLOAD)

    variant_set = _client(handler).variants(6, 29)
    assert variant_set.colors == ["Black"]
    assert variant_set.placeholder("front") is not None


def test_placeholders_are_read_from_inside_each_variant() -> None:
    """The bug: they were read from a top-level `placeholders` key that the
    response does not have, so every set came back with none and `new` died
    with "has no 'front' placeholder. Available: (none)"."""
    variant_set = _client(lambda request: httpx.Response(200, json=VARIANTS_PAYLOAD)).variants(
        6, 29
    )

    assert "placeholders" not in VARIANTS_PAYLOAD  # the key it used to look for
    assert sorted(variant_set.positions()) == ["back", "front"]
    assert [(v.id, len(v.placeholders)) for v in variant_set.variants] == [(1, 2), (2, 2)]


def test_the_largest_print_area_wins_when_sizes_differ() -> None:
    """Print areas differ per garment size and a profile carries exactly one,
    so `new` records the largest: art sized for the 3XL panel still covers the
    S panel, and the reverse prints soft where it matters most."""
    variant_set = _client(lambda request: httpx.Response(200, json=VARIANTS_PAYLOAD)).variants(
        6, 29
    )

    front = variant_set.placeholder("front")
    assert front is not None
    assert (front.width, front.height) == (4200, 4800)
    assert [(p.width, p.height) for p in variant_set.placeholder_sizes("front")] == [
        (4200, 4800),
        (3461, 3955),
    ]


def test_fields_printify_adds_later_are_ignored_not_fatal() -> None:
    """`decoration_method`/`decoration_methods` are in the real payload and
    mean nothing here. A third-party payload grows fields; decoding must not
    break when it does."""
    variant_set = _client(lambda request: httpx.Response(200, json=VARIANTS_PAYLOAD)).variants(
        6, 29
    )
    assert variant_set.variants[0].placeholders[0].position == "front"


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_credentials_become_an_actionable_error(status: int) -> None:
    """A raw ``HTTPStatusError`` traceback tells the user nothing about what to
    do. The decoded error has to name the token, the scope and the file."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "Unauthenticated."})

    with pytest.raises(CatalogAuthError) as exc_info:
        _client(handler).blueprints()

    message = str(exc_info.value)
    assert "PRINTIFY_API_TOKEN" in message
    assert "catalog.read" in message


def test_other_http_errors_are_not_swallowed_as_auth_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(httpx.HTTPStatusError):
        _client(handler).blueprints()


def test_token_is_resolved_lazily_so_a_cache_hit_never_needs_one() -> None:
    """``plan``/``apply`` build a catalog client eagerly but never call it in
    Phase 0/1. Resolving the token at construction time would have made every
    ``plan`` in a workspace with no ``.env`` fail."""
    calls: list[int] = []

    def token() -> str:
        calls.append(1)
        return "lazy-token"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=BLUEPRINTS_PAYLOAD)

    transport = httpx.MockTransport(handler)
    client = HttpCatalogClient(token, client=httpx.Client(transport=transport, base_url=BASE_URL))
    assert calls == []
    client.blueprints()
    assert calls == [1]


def test_secrets_read_the_workspace_env_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("PRINTIFY_API_TOKEN", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("PRINTIFY_API_TOKEN=from-dotenv\n", encoding="utf-8")
    secrets = Secrets.load(env_file)
    assert secrets.require_printify_api_token() == "from-dotenv"


def test_missing_token_names_the_file_it_should_be_in(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("PRINTIFY_API_TOKEN", raising=False)
    secrets = Secrets.load(tmp_path / ".env")
    with pytest.raises(MissingCredentialError) as exc_info:
        secrets.require_printify_api_token()
    message = str(exc_info.value)
    assert "PRINTIFY_API_TOKEN" in message
    assert str(tmp_path / ".env") in message
