"""The Admin page's Shop endpoints over a copy of the fixture workspace.

Admin plan, PR 3: reads carry a revision, saves are revision-checked and
validated as a whole document, refusals keep the file as it was, and live
lookups fail as an answer rather than a 500. Etsy and Printify are fakes.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from etsy_listings.core import connections
from etsy_listings.core.clients.etsy.fakes import FakeEtsyListingClient, FakeEtsyShopClient
from etsy_listings.core.clients.etsy.models import ShippingProfile
from etsy_listings.core.clients.etsy.transport import EtsyApiError
from etsy_listings.core.clients.printify import FakeCatalogClient, PrintProvider
from etsy_listings.core.clients.printify.fakes import FakePrintifyClient
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

from tests.support.builders import set_etsy_shop_id


@pytest.fixture
def client(workspace_root: Path) -> TestClient:
    return TestClient(create_app(Workspace.discover(root_override=workspace_root)))


def shop_bytes(root: Path) -> bytes:
    return (root / layout.SHOP_FILE).read_bytes()


def test_the_shop_read_carries_its_revision_values_and_currencies(
    client: TestClient, workspace_root: Path
) -> None:
    body = client.get("/api/admin/shop").json()

    assert body["revision"] == hashlib.sha256(shop_bytes(workspace_root)).hexdigest()
    assert body["currency"] == "NOK"
    assert body["listing_defaults"]["who_made"] == "i_did"
    assert body["preferred_print_provider"] == "Monster Digital"
    assert {"code": "NOK", "name": "Norwegian krone"} in body["supported_currencies"]
    assert "VND" not in {c["code"] for c in body["supported_currencies"]}


def test_a_save_returns_the_new_revision_for_the_next_one(
    client: TestClient, workspace_root: Path
) -> None:
    revision = client.get("/api/admin/shop").json()["revision"]

    saved = client.patch(
        "/api/admin/shop",
        json={"revision": revision, "changes": {"renewal": "auto", "currency": "EUR"}},
    )

    assert saved.status_code == 200
    body = saved.json()
    assert body["revision"] == hashlib.sha256(shop_bytes(workspace_root)).hexdigest()
    assert (body["listing_defaults"]["renewal"], body["currency"]) == ("auto", "EUR")
    again = client.patch(
        "/api/admin/shop", json={"revision": body["revision"], "changes": {"renewal": "manual"}}
    )
    assert again.status_code == 200


def test_a_stale_save_is_a_conflict_and_writes_nothing(
    client: TestClient, workspace_root: Path
) -> None:
    revision = client.get("/api/admin/shop").json()["revision"]
    edited = shop_bytes(workspace_root) + b"# a comment from an editor\n"
    (workspace_root / layout.SHOP_FILE).write_bytes(edited)

    refused = client.patch(
        "/api/admin/shop", json={"revision": revision, "changes": {"renewal": "auto"}}
    )

    assert refused.status_code == 409
    assert refused.json()["kind"] == "conflict"
    assert shop_bytes(workspace_root) == edited


def test_an_invalid_value_names_its_field_and_writes_nothing(
    client: TestClient, workspace_root: Path
) -> None:
    original = shop_bytes(workspace_root)
    revision = client.get("/api/admin/shop").json()["revision"]

    refused = client.patch(
        "/api/admin/shop", json={"revision": revision, "changes": {"renewal": "weekly"}}
    )

    assert refused.status_code == 422
    body = refused.json()
    assert body["kind"] == "invalid"
    assert list(body["field_errors"]) == ["etsy.listing_defaults.renewal"]
    assert shop_bytes(workspace_root) == original


def test_saving_the_current_values_changes_nothing(
    client: TestClient, workspace_root: Path
) -> None:
    original = shop_bytes(workspace_root)
    revision = client.get("/api/admin/shop").json()["revision"]

    saved = client.patch(
        "/api/admin/shop",
        json={"revision": revision, "changes": {"currency": "NOK", "is_supply": False}},
    )

    assert saved.json()["revision"] == revision
    assert shop_bytes(workspace_root) == original


def test_a_return_policy_round_trips_as_terms(client: TestClient) -> None:
    revision = client.get("/api/admin/shop").json()["revision"]
    terms = {"accepts_returns": True, "accepts_exchanges": True, "within_days": 14}

    saved = client.patch(
        "/api/admin/shop", json={"revision": revision, "changes": {"return_policy": terms}}
    )

    assert saved.json()["listing_defaults"]["return_policy"] == terms


def test_lookups_answer_each_service_separately(
    client: TestClient, workspace_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_etsy_shop_id(workspace_root, 51007712)
    client = TestClient(create_app(Workspace.discover(root_override=workspace_root)))

    class Down(FakeEtsyListingClient):
        def production_partners(self, shop_id: int) -> list:  # type: ignore[type-arg]
            raise EtsyApiError(503, error="Etsy is down")

    monkeypatch.setattr(connections, "etsy_listing_client", lambda root: Down())
    monkeypatch.setattr(
        connections,
        "catalog_client",
        lambda workspace: FakeCatalogClient(
            [], {}, {}, all_providers=[PrintProvider(id=3, title="SwiftPOD")]
        ),
    )

    body = client.get("/api/admin/shop/lookups").json()

    assert body["etsy"]["available"] is False
    assert "Etsy is down" in body["etsy"]["problem"]
    assert body["printify"] == {
        "available": True,
        "problem": None,
        "print_providers": ["SwiftPOD"],
    }


def test_lookups_list_the_shops_choices(
    workspace_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_etsy_shop_id(workspace_root, 51007712)
    client = TestClient(create_app(Workspace.discover(root_override=workspace_root)))
    etsy = FakeEtsyListingClient(
        shipping_profiles=[ShippingProfile(shipping_profile_id=1, title="Standard")]
    )
    monkeypatch.setattr(connections, "etsy_listing_client", lambda root: etsy)
    monkeypatch.setattr(
        connections, "catalog_client", lambda workspace: FakeCatalogClient([], {}, {})
    )

    body = client.get("/api/admin/shop/lookups").json()

    assert body["etsy"]["shipping_profiles"] == ["Standard"]
    assert body["etsy"]["return_policies"] == []


def test_connections_say_what_to_run_when_nothing_is_set_up(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(connections, "etsy_shop_client", lambda root: FakeEtsyShopClient())
    monkeypatch.setattr(connections, "printify_client", lambda workspace: FakePrintifyClient())

    body = client.get("/api/admin/shop/connections").json()

    assert body["etsy"]["state"] == "not_connected"
    assert body["etsy"]["shop_name"] == "TakeAHikeTees"
    assert body["etsy"]["commands"] == ["etsy-listings auth etsy", "etsy-listings setup"]
    assert body["printify"]["commands"] == ["etsy-listings auth printify", "etsy-listings setup"]
