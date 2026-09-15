"""Behaviour tests for the listings UI's FastAPI endpoints (phase 5), against
a writable copy of the fixture workspace -- same pattern as
``test_calibrator_api.py``: real files on disk, no network, no fakes.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from PIL import Image

from etsy_listings.engine.lock import Lockfile
from etsy_listings.ui.api.app import create_app
from etsy_listings.workspace.workspace import Workspace


@pytest.fixture
def client(workspace_root: Path) -> TestClient:
    workspace = Workspace.discover(root_override=workspace_root)
    return TestClient(create_app(workspace))


def _write_pricing_plan(
    workspace_root: Path, name: str, garment_profile: str, prices: dict[str, str]
) -> Path:
    path = workspace_root / "pricing-plans" / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {"garment_profile": garment_profile, "prices": prices, "price_overrides": {}}
        ),
        encoding="utf-8",
    )
    return path


class TestListListings:
    def test_includes_the_fixture_listing(self, client: TestClient) -> None:
        response = client.get("/api/listings")
        assert response.status_code == 200
        by_name = {row["name"]: row for row in response.json()}
        row = by_name["take-a-hike"]
        assert row["garment_profile"] == "comfort-colors-1717"
        assert row["colour_count"] == 4
        assert row["status"] == "draft"

    def test_a_row_names_the_design_its_thumbnail_is_addressed_by(self, client: TestClient) -> None:
        """The table shows the artwork, so a row has to carry the name
        `GET /api/listing-designs/{name}/thumbnail` takes -- the stem, not
        the ``../../designs/take-a-hike.png`` ref stored in listing.yaml."""
        row = {r["name"]: r for r in client.get("/api/listings").json()}["take-a-hike"]
        assert row["design"] == "take-a-hike"
        assert client.get(f"/api/listing-designs/{row['design']}/thumbnail").status_code == 200

    def test_a_row_with_a_multi_artwork_design_has_no_single_thumbnail(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        """A design keyed ``on-light``/``on-dark`` has no one picture that
        stands for the listing, and picking an arbitrary key would show the
        wrong ink half the time. ``None`` -- the row falls back to a
        placeholder rather than lying."""
        path = workspace_root / "listings" / "take-a-hike" / "listing.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        raw["design"] = {
            "on-light": "../../designs/take-a-hike.png",
            "on-dark": "../../designs/take-a-hike.png",
        }
        path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

        row = {r["name"]: r for r in client.get("/api/listings").json()}["take-a-hike"]
        assert row["design"] is None

    def test_a_published_row_carries_the_ids_its_open_menu_links_to(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        """The table offers "Open on Etsy / Open on Printify" on a published
        row, the same menu the editor's page head has. Carried on the summary
        so the menu costs no extra request per row."""
        lock = Lockfile.empty(tool_version="test", applied_at="2024-01-01T00:00:00")
        lock = lock.model_copy(
            update={"remote": {"etsy_listing_id": 555, "printify_product_id": "abc123"}}
        )
        lock.write(workspace_root / "listings" / "take-a-hike" / "state.lock.json")

        row = {r["name"]: r for r in client.get("/api/listings").json()}["take-a-hike"]
        assert row["etsy_listing_id"] == 555
        assert row["printify_product_id"] == "abc123"

    def test_a_draft_row_has_no_remote_ids(self, client: TestClient) -> None:
        row = {r["name"]: r for r in client.get("/api/listings").json()}["take-a-hike"]
        assert row["etsy_listing_id"] is None
        assert row["printify_product_id"] is None

    def test_a_generate_title_and_an_undersized_design_both_count_as_blocking(
        self, client: TestClient
    ) -> None:
        """The fixture design (360x432) is far short of the garment's
        4500x5400 print area, and the copy is still the `<generate>`
        sentinel -- both are structural non-issues (valid `Listing`) but
        real business blockers."""
        row = {r["name"]: r for r in client.get("/api/listings").json()}["take-a-hike"]
        assert row["issue_counts"]["block"] >= 2


class TestGetListingDetail:
    def test_404s_for_an_unknown_listing(self, client: TestClient) -> None:
        assert client.get("/api/listings/does-not-exist").status_code == 404

    def test_returns_the_full_listing_document(self, client: TestClient) -> None:
        body = client.get("/api/listings/take-a-hike").json()
        assert body["name"] == "take-a-hike"
        assert body["garment_profile"] == "comfort-colors-1717"
        assert body["colors"] == ["black", "blue-jean", "ivory", "moss"]
        assert body["status"] == "draft"
        assert body["field_errors"] == {}

    def test_reports_the_generate_title_as_a_details_block(self, client: TestClient) -> None:
        issues = client.get("/api/listings/take-a-hike").json()["issues"]
        assert any(
            i["tab"] == "details" and i["severity"] == "block" and "title" in i["message"].lower()
            for i in issues
        )

    def test_reports_the_undersized_design_as_a_variants_block(self, client: TestClient) -> None:
        issues = client.get("/api/listings/take-a-hike").json()["issues"]
        matches = [i for i in issues if i["tab"] == "variants" and i["severity"] == "block"]
        assert any("360" in i["message"] for i in matches)

    def test_warns_about_colours_the_garment_profile_does_not_classify(
        self, client: TestClient
    ) -> None:
        """The fixture garment profile has an empty `colors:` dict, so every
        one of the listing's four colours is an unclassified proxy-warning."""
        issues = client.get("/api/listings/take-a-hike").json()["issues"]
        warning = next(i for i in issues if i["tab"] == "variants" and i["severity"] == "warn")
        assert all(c in warning["message"] for c in ["black", "blue-jean", "ivory", "moss"])

    def test_a_published_listing_carries_its_remote_ids(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        lock = Lockfile.empty(tool_version="test", applied_at="2024-01-01T00:00:00")
        lock = lock.model_copy(
            update={"remote": {"etsy_listing_id": 555, "printify_product_id": "abc123"}}
        )
        lock.write(workspace_root / "listings" / "take-a-hike" / "state.lock.json")

        body = client.get("/api/listings/take-a-hike").json()
        assert body["status"] == "published"
        assert body["etsy_listing_id"] == 555
        assert body["printify_product_id"] == "abc123"


class TestPatchListing:
    def test_404s_for_an_unknown_listing(self, client: TestClient) -> None:
        assert client.patch("/api/listings/does-not-exist", json={}).status_code == 404

    def test_updating_the_title_clears_its_own_issue(self, client: TestClient) -> None:
        response = client.patch(
            "/api/listings/take-a-hike", json={"etsy": {"title": "Take A Hike Tee"}}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["etsy"]["title"] == "Take A Hike Tee"
        assert not any(
            i["tab"] == "details" and "title" in i["message"].lower() for i in body["issues"]
        )

    def test_updating_the_title_leaves_sibling_etsy_fields_untouched(
        self, client: TestClient
    ) -> None:
        """The merge is one level deep on `etsy:` -- a PATCH touching only
        `title` must not silently reset `materials` (already non-default in
        the fixture) back to its schema default."""
        response = client.patch(
            "/api/listings/take-a-hike", json={"etsy": {"title": "Take A Hike Tee"}}
        )
        assert response.json()["etsy"]["materials"] == ["cotton"]

    def test_an_invalid_price_is_rejected_with_a_field_error_and_writes_nothing(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        listing_path = workspace_root / "listings" / "take-a-hike" / "listing.yaml"
        before = listing_path.read_text(encoding="utf-8")

        response = client.patch("/api/listings/take-a-hike", json={"prices": {"S": "not-a-price"}})
        assert response.status_code == 200
        body = response.json()
        assert body["field_errors"], "an unparseable price must be reported"
        assert listing_path.read_text(encoding="utf-8") == before

    def test_a_colour_out_of_range_for_its_kind_is_a_business_block(
        self, client: TestClient
    ) -> None:
        """`colour-chart-01` is a `multiple`-kind template in the fixture --
        naming a colour on it is a kind/colour mismatch, not a structural
        failure, so it lands in `issues`, not `field_errors`."""
        response = client.patch(
            "/api/listings/take-a-hike",
            json={"media": [{"template": "colour-chart-01", "colour": "black"}]},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["field_errors"] == {}
        assert any(i["tab"] == "images" and i["severity"] == "block" for i in body["issues"])


class TestCreateListing:
    def test_writes_a_minimal_valid_listing_and_returns_it(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        _write_pricing_plan(workspace_root, "tee-basic", "comfort-colors-1717", {"S": "349 NOK"})

        response = client.post(
            "/api/listings",
            json={
                "name": "my-new-shirt",
                "design": "take-a-hike",
                "garment_profile": "comfort-colors-1717",
                "colors": ["black"],
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "my-new-shirt"
        assert body["media"] == []
        assert body["colors"] == ["black"]
        assert body["design"] == {"default": "../../designs/take-a-hike.png"}

        written = workspace_root / "listings" / "my-new-shirt" / "listing.yaml"
        assert written.is_file()

    def test_conflicts_with_an_existing_listing_name(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        _write_pricing_plan(workspace_root, "tee-basic", "comfort-colors-1717", {"S": "349 NOK"})
        response = client.post(
            "/api/listings",
            json={
                "name": "take-a-hike",
                "design": "take-a-hike",
                "garment_profile": "comfort-colors-1717",
                "colors": ["black"],
            },
        )
        assert response.status_code == 409

    def test_refuses_an_unknown_design(self, client: TestClient, workspace_root: Path) -> None:
        _write_pricing_plan(workspace_root, "tee-basic", "comfort-colors-1717", {"S": "349 NOK"})
        response = client.post(
            "/api/listings",
            json={
                "name": "brand-new",
                "design": "no-such-design",
                "garment_profile": "comfort-colors-1717",
                "colors": ["black"],
            },
        )
        assert response.status_code == 400

    def test_refuses_an_unknown_garment_profile(self, client: TestClient) -> None:
        response = client.post(
            "/api/listings",
            json={
                "name": "brand-new",
                "design": "take-a-hike",
                "garment_profile": "no-such-profile",
                "colors": ["black"],
            },
        )
        assert response.status_code == 400

    def test_refuses_when_no_compatible_pricing_plan_exists(self, client: TestClient) -> None:
        """The fixture workspace has no `pricing-plans/` at all."""
        response = client.post(
            "/api/listings",
            json={
                "name": "brand-new",
                "design": "take-a-hike",
                "garment_profile": "comfort-colors-1717",
                "colors": ["black"],
            },
        )
        assert response.status_code == 400
        assert "pricing plan" in response.json()["detail"]


class TestSupportingEndpoints:
    def test_lists_garment_profiles(self, client: TestClient) -> None:
        response = client.get("/api/garment-profiles")
        assert response.status_code == 200
        by_name = {row["name"]: row for row in response.json()}
        assert by_name["comfort-colors-1717"]["sizes"] == ["S", "M", "L", "XL", "XXL", "XXXL"]

    def test_lists_pricing_plans_marking_the_compatible_one(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        _write_pricing_plan(workspace_root, "tee-basic", "comfort-colors-1717", {"S": "349 NOK"})
        _write_pricing_plan(workspace_root, "other-garment", "some-other-profile", {"S": "349 NOK"})

        response = client.get(
            "/api/pricing-plans", params={"garment_profile": "comfort-colors-1717"}
        )
        assert response.status_code == 200
        by_name = {row["name"]: row for row in response.json()}
        assert by_name["tee-basic"]["compatible"] is True
        assert by_name["other-garment"]["compatible"] is False

    def test_lists_listing_designs(self, client: TestClient) -> None:
        response = client.get("/api/listing-designs")
        assert response.status_code == 200
        by_name = {row["name"]: row for row in response.json()}
        assert by_name["take-a-hike"]["file"] == "designs/take-a-hike.png"

    def test_serves_a_design_thumbnail(self, client: TestClient) -> None:
        """The listings table, its hover card and the editor's design strip
        all show the artwork. Downscaled for the same reason the template
        rail's is: a table of full-size PNGs would cost as much as the page."""
        response = client.get("/api/listing-designs/take-a-hike/thumbnail")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        with Image.open(BytesIO(response.content)) as img:
            assert max(img.size) <= 160

    def test_a_design_thumbnail_404s_for_an_unknown_design(self, client: TestClient) -> None:
        assert client.get("/api/listing-designs/no-such-art/thumbnail").status_code == 404

    def test_names_the_shop_the_sidebar_says_you_are_working_on(self, client: TestClient) -> None:
        """One workspace per shop, so the sidebar says which -- the difference
        between a test shop and the real one is worth seeing before an edit,
        not after an apply."""
        response = client.get("/api/workspace")
        assert response.status_code == 200
        assert response.json()["shop_name"] == "TakeAHikeTees"

    def test_reports_a_shop_with_no_name_yet_rather_than_failing(
        self, workspace_root: Path
    ) -> None:
        """`etsy.shop_name` arrives from Etsy during `setup`, so a workspace
        that has only ever rendered mockups has none.

        Builds its own client rather than taking the fixture: ``shop.yaml`` is
        read once, at ``Workspace.discover``, so editing it afterwards would
        change nothing this request can see.
        """
        path = workspace_root / "shop.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        del raw["etsy"]["shop_name"]
        path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

        nameless = TestClient(create_app(Workspace.discover(root_override=workspace_root)))
        response = nameless.get("/api/workspace")
        assert response.status_code == 200
        assert response.json()["shop_name"] is None
