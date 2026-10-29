"""Saving a listing composes its gallery scenes in the background, so the
Listing Images tab's full-size previews are already in the scene cache."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from etsy_listings.core.application import prepared_previews
from etsy_listings.core.application.scene_warming import SceneWarmer
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

from tests.support.builders import FIXTURE_LISTING
from tests.support.scenes import expected_scene

DESIGN = "designs/take-a-hike.png"


@pytest.fixture
def client(workspace_root: Path) -> Iterator[TestClient]:
    with TestClient(create_app(Workspace.discover(root_override=workspace_root))) as client:
        yield client


def _cached_after_warming(client: TestClient, root: Path) -> set[bytes]:
    warmer: SceneWarmer = client.app.state.scene_warmer  # type: ignore[attr-defined]
    assert warmer.wait_idle(timeout=30)
    cache = Workspace.discover(root_override=root).scene_cache_dir()
    return {path.read_bytes() for path in cache.rglob("*") if path.is_file()}


def test_a_saved_gallery_scene_is_cached_before_it_is_asked_for(
    client: TestClient, workspace_root: Path
) -> None:
    response = client.patch(
        f"/api/listings/{FIXTURE_LISTING}",
        json={"media": [{"template": "flat-lay-01", "colour": "moss"}]},
    )
    assert response.status_code == 200

    assert _cached_after_warming(client, workspace_root) == {
        expected_scene(workspace_root, "flat-lay-01", "moss", {"moss": DESIGN})
    }


def test_the_preview_of_a_warmed_scene_composes_nothing(
    client: TestClient, workspace_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The warmer stores under the identity the preview endpoint looks up."""
    client.patch(
        f"/api/listings/{FIXTURE_LISTING}",
        json={"media": [{"template": "flat-lay-01", "colour": "moss"}]},
    )
    (warmed,) = _cached_after_warming(client, workspace_root)

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("composed a scene the warmer had cached")

    monkeypatch.setattr(prepared_previews, "compose_preview", refuse)
    response = client.get(
        f"/api/listings/{FIXTURE_LISTING}/scene-preview",
        params={"template": "flat-lay-01", "colour": "moss"},
    )

    assert response.status_code == 200
    assert response.content == warmed


def test_a_created_listing_is_warmed(client: TestClient, workspace_root: Path) -> None:
    document = {
        "garment_profile": "comfort-colors-1717",
        "design": DESIGN,
        "colors": ["black"],
        "brief": "",
        "prices": {"S": "349 NOK"},
        "media": [{"template": "flat-lay-01", "colour": "black"}],
    }

    response = client.post("/api/listings", json={"name": "fresh", "document": document})
    assert response.status_code == 200

    assert _cached_after_warming(client, workspace_root) == {
        expected_scene(workspace_root, "flat-lay-01", "black", {"black": DESIGN})
    }


def test_a_refused_save_warms_nothing(client: TestClient, workspace_root: Path) -> None:
    response = client.patch(
        f"/api/listings/{FIXTURE_LISTING}", json={"prices": {"S": "not-a-price"}}
    )
    assert response.json()["field_errors"]

    assert _cached_after_warming(client, workspace_root) == set()
