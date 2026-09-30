"""The listing-templates resource's HTTP surface (ADR-0047, template completeness; batch plan PR 1):
status codes, payload shape, and -- because a refusal must never half-write
-- what is on disk after each answer.

Through a real ``TestClient`` against a writable copy of the fixture
workspace. The saving rules themselves are `listing_templates`' and are
unit-tested there; these pin what the browser is told.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from etsy_listings.core.batches import Batch
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.ui.api.app import create_app

from tests.support.batches import png
from tests.support.builders import FIXTURE_LISTING, edit_garment_profile, edit_listing

NAME = "heavyweight-tee"
BLACK = {"template": "flat-lay-01", "colour": "black"}


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


@pytest.fixture
def client(workspace: Workspace) -> TestClient:
    return TestClient(create_app(workspace))


def _create(client: TestClient, name: str = NAME, **source: str) -> Any:  # noqa: ANN401
    return client.post(
        "/api/listing-templates",
        json={"name": name, **(source or {"from_listing": FIXTURE_LISTING})},
    )


def _local_picture(workspace: Workspace, ref: str) -> None:
    path = workspace.listing_dir(FIXTURE_LISTING) / ref.removeprefix("./")
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (400, 300), (200, 180, 150)).save(path)


class TestCreate:
    def test_saving_a_listing_writes_the_template_and_answers_it(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        response = _create(client)

        assert response.status_code == 200
        body = response.json()
        assert body["saved"] is True
        assert body["template"]["name"] == NAME
        assert body["template"]["colors"] == ["black", "blue-jean", "ivory", "moss"]
        assert workspace.listing_template_names() == [NAME]

    def test_a_name_clash_is_a_409_with_nothing_written(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        _create(client)
        before = workspace.listing_template_file(NAME).read_bytes()
        edit_listing(
            workspace.root, colors=["black"], media=[{"template": "flat-lay-01", "colour": "black"}]
        )

        response = _create(client)

        assert response.status_code == 409
        assert NAME in response.json()["detail"]
        assert workspace.listing_template_file(NAME).read_bytes() == before

    def test_an_incomplete_listing_is_refused_with_its_issues(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        edit_listing(workspace.root, colors=[], media=["common-media/size-guide.png"])

        response = _create(client)

        assert response.status_code == 200
        body = response.json()
        assert body["saved"] is False
        assert body["template"] is None
        assert {"severity": "block", "where": "Variants › Colours"}.items() <= body["issues"][
            0
        ].items()
        assert not workspace.listing_template_dir(NAME).exists()

    def test_an_unreadable_local_file_is_a_422_naming_the_ref(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        edit_listing(
            workspace.root,
            media=[{"template": "flat-lay-01", "colour": "black"}, "./shots/gone.png"],
        )

        response = _create(client)

        assert response.status_code == 422
        assert "./shots/gone.png" in response.json()["detail"]
        assert not workspace.listing_templates_dir().exists()

    def test_a_missing_source_is_a_404(self, client: TestClient) -> None:
        assert _create(client, from_listing="no-such-listing").status_code == 404
        assert _create(client, from_template="no-such-template").status_code == 404

    def test_exactly_one_source_is_required(self, client: TestClient) -> None:
        both = client.post(
            "/api/listing-templates",
            json={"name": NAME, "from_listing": FIXTURE_LISTING, "from_template": "x"},
        )
        neither = client.post("/api/listing-templates", json={"name": NAME})

        assert both.status_code == 422
        assert neither.status_code == 422

    def test_a_name_that_is_not_one_segment_is_a_400(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        assert _create(client, name="../escape").status_code == 400
        assert _create(client, name="draft").status_code == 400  # GET /draft's path
        assert not workspace.listing_templates_dir().exists()

    def test_edits_made_before_naming_are_what_is_written(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        """The *name it* state is the editor (UI doc §1, §3): what the
        seller changed before naming it is saved, and a file the edit
        dropped is not copied."""
        _local_picture(workspace, "./shots/back.png")
        edit_listing(
            workspace.root,
            media=[{"template": "flat-lay-01", "colour": "black"}, "./shots/back.png"],
        )
        draft = client.get(f"/api/listing-templates/draft?from_listing={FIXTURE_LISTING}").json()

        response = client.post(
            "/api/listing-templates",
            json={
                "name": NAME,
                "from_listing": FIXTURE_LISTING,
                "document": {**_document(draft), "colors": ["black"], "media": [BLACK]},
            },
        )

        assert response.json()["saved"] is True
        assert workspace.load_listing_template(NAME).colors == ["black"]
        assert not workspace.listing_template_assets_dir(NAME).exists()

    def test_an_edited_document_is_checked_like_a_put(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        draft = client.get(f"/api/listing-templates/draft?from_listing={FIXTURE_LISTING}").json()

        def create(document: dict[str, Any]) -> Any:  # noqa: ANN401
            return client.post(
                "/api/listing-templates",
                json={"name": NAME, "from_listing": FIXTURE_LISTING, "document": document},
            )

        incomplete = create(
            {**_document(draft), "colors": [], "media": ["common-media/size-guide.png"]}
        )
        malformed = create({**_document(draft), "brief": "no"})
        unplanned = create({**_document(draft), "media": [BLACK, "./assets/elsewhere.png"]})

        assert incomplete.json()["saved"] is False
        assert "brief" in malformed.json()["field_errors"]
        assert unplanned.status_code == 422
        assert "./assets/elsewhere.png" in unplanned.json()["detail"]
        assert not workspace.listing_templates_dir().exists()

    def test_a_clone_is_created_from_another_template(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        _create(client)

        response = _create(client, name="everyday-tee", from_template=NAME)

        assert response.json()["saved"] is True
        assert workspace.listing_template_names() == ["everyday-tee", NAME]


class TestDraft:
    def test_the_draft_is_the_template_as_it_would_be_saved_and_writes_nothing(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        _local_picture(workspace, "./shots/back.png")
        edit_listing(
            workspace.root,
            media=[{"template": "flat-lay-01", "colour": "black"}, "./shots/back.png"],
            etsy={"title": "Take A Hike", "description": {"lead": "Retro.", "text": "Cotton."}},
        )

        response = client.get(f"/api/listing-templates/draft?from_listing={FIXTURE_LISTING}")

        assert response.status_code == 200
        body = response.json()
        assert body["source"] == {"kind": "listing", "name": FIXTURE_LISTING}
        assert body["media"][1] == "./assets/shots/back.png"
        assert body["assets"] == [
            {"ref": "./assets/shots/back.png", "source_ref": "./shots/back.png"}
        ]
        assert body["etsy"]["description"] == {"text": "Cotton.", "ref": None}
        assert "title" not in body["etsy"]
        assert body["garment"] == "Comfort Colors 1717"
        assert not workspace.listing_templates_dir().exists()

    def test_a_draft_needs_exactly_one_source_that_exists(self, client: TestClient) -> None:
        _create(client)
        clone = client.get(f"/api/listing-templates/draft?from_template={NAME}").json()

        assert clone["source"] == {"kind": "listing-template", "name": NAME}
        assert client.get("/api/listing-templates/draft").status_code == 422
        missing = client.get("/api/listing-templates/draft?from_listing=no-such-listing")
        assert missing.status_code == 404


class TestReadAndDelete:
    def test_the_index_has_what_a_card_shows(self, client: TestClient) -> None:
        _create(client)

        [card] = client.get("/api/listing-templates").json()

        assert card["name"] == NAME
        assert card["garment"] == "Comfort Colors 1717"
        assert card["colour_count"] == 4
        assert card["pricing_plan_name"] is None
        assert len(card["media"]) == 4
        assert card["batch_count"] == 0

    def test_one_template_reads_back_with_its_issues(self, client: TestClient) -> None:
        _create(client)

        response = client.get(f"/api/listing-templates/{NAME}")

        assert response.status_code == 200
        assert response.json()["name"] == NAME
        assert response.json()["modified_at"] is not None
        assert client.get("/api/listing-templates/nothing-here").status_code == 404

    def test_a_template_reads_back_with_what_the_listing_editor_s_tabs_show(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        """The listing-template editor mounts the listing editor's own tabs
        (UI doc §3), so a template carries the same computed fields a
        listing's detail does: resolved prices per size, the garment's
        materials and the composed description."""
        edit_listing(workspace.root, etsy={"description": {"lead": "", "text": "Cotton."}})
        _create(client)

        body = client.get(f"/api/listing-templates/{NAME}").json()

        assert body["resolved_prices"][:2] == [
            {"size": "S", "amount": "349 NOK"},
            {"size": "M", "amount": "349 NOK"},
        ]
        assert body["garment_materials"] == ["cotton"]
        assert body["garment_brand"] == "Comfort Colors"
        assert body["description_composed"] == "Cotton."

    def test_delete_removes_the_template(self, client: TestClient, workspace: Workspace) -> None:
        _create(client)

        assert client.delete(f"/api/listing-templates/{NAME}").status_code == 204
        assert not workspace.listing_template_dir(NAME).exists()
        assert client.delete(f"/api/listing-templates/{NAME}").status_code == 404

    def test_a_template_s_own_picture_is_served_and_its_file_is_not(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        _local_picture(workspace, "./shots/back.png")
        edit_listing(
            workspace.root,
            media=[{"template": "flat-lay-01", "colour": "black"}, "./shots/back.png"],
        )
        _create(client)
        base = f"/api/listing-templates/{NAME}/media-files"

        thumbnail = client.get(f"{base}/assets/shots/back.png/thumbnail")
        full = client.get(f"{base}/assets/shots/back.png/file")

        assert thumbnail.status_code == 200
        assert thumbnail.headers["content-type"] == "image/png"
        assert full.status_code == 200
        assert client.get(f"{base}/template.yaml/file").status_code == 400
        assert client.get(f"{base}/assets/gone.png/file").status_code == 404


class TestPut:
    """valid-only save. The editor that drives it is PR 6's; the
    contract is fixed now so a template on disk is never incomplete."""

    def test_an_incomplete_document_is_not_saved_and_the_file_is_untouched(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        document = _create(client).json()["template"]
        before = workspace.listing_template_file(NAME).read_bytes()

        response = client.put(
            f"/api/listing-templates/{NAME}",
            json={**_document(document), "colors": [], "media": ["common-media/size-guide.png"]},
        )

        assert response.status_code == 200
        assert response.json()["saved"] is False
        assert response.json()["issues"][0]["where"] == "Variants › Colours"
        assert workspace.listing_template_file(NAME).read_bytes() == before

    def test_a_malformed_document_is_not_saved(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        document = _create(client).json()["template"]
        before = workspace.listing_template_file(NAME).read_bytes()

        response = client.put(
            f"/api/listing-templates/{NAME}", json={**_document(document), "brief": "no"}
        )

        assert response.json()["saved"] is False
        assert "brief" in response.json()["field_errors"]
        assert workspace.listing_template_file(NAME).read_bytes() == before

    def test_a_complete_document_is_written(self, client: TestClient, workspace: Workspace) -> None:
        document = _create(client).json()["template"]

        response = client.put(
            f"/api/listing-templates/{NAME}",
            json={**_document(document), "colors": ["black"], "media": [BLACK]},
        )

        assert response.json()["saved"] is True
        assert workspace.load_listing_template(NAME).colors == ["black"]


class TestRename:
    """Double-click the name, exactly like a listing (UI doc §3): the
    directory moves whole, and a taken name is refused, never suffixed."""

    def test_rename_moves_the_template_and_its_own_files(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        _local_picture(workspace, "./shots/back.png")
        edit_listing(
            workspace.root,
            media=[{"template": "flat-lay-01", "colour": "black"}, "./shots/back.png"],
        )
        _create(client)

        response = client.post(
            f"/api/listing-templates/{NAME}/rename", json={"new_name": "everyday-tee"}
        )

        assert response.status_code == 200
        assert response.json()["name"] == "everyday-tee"
        assert workspace.listing_template_names() == ["everyday-tee"]
        assert workspace.listing_template_media_file(
            "everyday-tee", "assets/shots/back.png"
        ).is_file()

    def test_batches_and_staging_made_from_it_follow_the_rename(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        """The card's *Used by N batches* is the seller's link between a
        template and its batches, so a rename carries it; the frozen copies
        themselves are left exactly as they were (spec, *Frozen staging*)."""
        _create(client)
        batch = Batch(
            id="b1",
            listing_template=NAME,
            template={"frozen": True},
            template_saved_at=datetime.now(UTC),
            label="heavyweight-tee · 27 Sep 11:42",
            created_at=datetime.now(UTC),
            rows=[],
        )
        client.app.state.batch_store.save(batch)  # type: ignore[attr-defined]
        edit_garment_profile(
            workspace.root, "comfort-colors-1717", print_area={"width": 100, "height": 120}
        )
        staged = client.post(
            "/api/staging",
            data={"listing_template": NAME},
            files=[("files", ("night-hike.png", png(1), "image/png"))],
        ).json()

        client.post(f"/api/listing-templates/{NAME}/rename", json={"new_name": "everyday-tee"})

        [card] = client.get("/api/listing-templates").json()
        assert card["name"] == "everyday-tee"
        assert card["batch_count"] == 1
        assert client.get("/api/batches/b1").json()["listing_template"] == "everyday-tee"
        assert (
            client.get(f"/api/staging/{staged['id']}").json()["listing_template"] == "everyday-tee"
        )
        record = client.app.state.batch_store.load("b1")  # type: ignore[attr-defined]
        assert record.template == {"frozen": True}
        assert record.label == "heavyweight-tee · 27 Sep 11:42"

    def test_a_taken_name_is_a_409_and_nothing_moves(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        _create(client)
        _create(client, name="everyday-tee", from_template=NAME)

        response = client.post(
            f"/api/listing-templates/{NAME}/rename", json={"new_name": "everyday-tee"}
        )

        assert response.status_code == 409
        assert workspace.listing_template_names() == ["everyday-tee", NAME]

    def test_the_same_name_is_not_a_clash(self, client: TestClient) -> None:
        _create(client)

        response = client.post(f"/api/listing-templates/{NAME}/rename", json={"new_name": NAME})

        assert response.status_code == 200

    def test_bad_names_and_missing_templates_are_refused(self, client: TestClient) -> None:
        _create(client)
        rename = f"/api/listing-templates/{NAME}/rename"

        assert client.post(rename, json={"new_name": "../escape"}).status_code == 400
        assert client.post(rename, json={"new_name": "draft"}).status_code == 400
        missing = client.post("/api/listing-templates/gone/rename", json={"new_name": "x"})
        assert missing.status_code == 404


class TestMediaFiles:
    def test_the_template_s_files_are_its_assets_only(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        """The Images tab's *This template* group (UI doc, *Existing
        components*): what is under ``assets/``, never ``template.yaml``."""
        _local_picture(workspace, "./shots/back.png")
        edit_listing(
            workspace.root,
            media=[{"template": "flat-lay-01", "colour": "black"}, "./shots/back.png"],
        )
        _create(client)
        Image.new("RGB", (40, 30)).save(workspace.listing_template_dir(NAME) / "stray.png")

        response = client.get(f"/api/listing-templates/{NAME}/media-files")

        assert response.status_code == 200
        assert response.json() == [
            {
                "name": "assets/shots/back.png",
                "file": f"listing-templates/{NAME}/assets/shots/back.png",
                "ref": "./assets/shots/back.png",
                "kind": "image",
            }
        ]
        assert client.get("/api/listing-templates/gone/media-files").status_code == 404


def _document(detail: dict[str, Any]) -> dict[str, Any]:
    """The `template.yaml` fields out of a detail response."""
    keys = ("garment_profile", "colors", "prices", "pricing_plan", "price_overrides", "etsy")
    return {key: detail[key] for key in keys} | {"media": detail["media"]}
