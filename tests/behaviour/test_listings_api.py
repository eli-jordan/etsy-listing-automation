"""Behaviour tests for the listings UI's FastAPI endpoints (phase 5), against
a writable copy of the fixture workspace -- same pattern as
``test_calibrator_api.py``: real files on disk, no network, no fakes.
"""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from PIL import Image

from etsy_listings import connections
from etsy_listings.clients.etsy.fakes import FakeEtsyListingClient, FakeEtsyShopClient
from etsy_listings.clients.etsy.models import ShopSection
from etsy_listings.engine.lock import Lockfile
from etsy_listings.ui.api import etsystate
from etsy_listings.ui.api.app import create_app
from etsy_listings.workspace.workspace import Workspace

from tests.support.builders import (
    copy_listing,
    edit_garment_profile,
    edit_listing,
    listing_file,
    set_etsy_shop_id,
)

VIDEOS = Path(__file__).parent.parent / "fixtures" / "video"


@pytest.fixture
def client(workspace_root: Path) -> TestClient:
    workspace = Workspace.discover(root_override=workspace_root)
    return TestClient(create_app(workspace))


@pytest.fixture(autouse=True)
def _no_remembered_etsy_states() -> Iterator[None]:
    """`etsystate`'s memo is process-wide on purpose (one `ui` process, one
    workspace), which makes it shared state between tests. Cleared either side
    so a listing id that meant "live" in one test does not mean it in the
    next."""
    etsystate.forget()
    yield
    etsystate.forget()


def write_lock(
    workspace_root: Path,
    name: str,
    *,
    etsy_listing_id: int | None = None,
    product_id: str | None = None,
    applied: bool = True,
    incomplete: bool = False,
) -> Path:
    """A lockfile for *name*, as an apply would have left it.

    ``applied`` is what separates "this listing has been through the pipeline"
    from "something wrote a lockfile carrying only ids" -- `stages_completed`
    is the record of the former, and it is what `draft` vs `deployed` turns on.

    ``incomplete`` stands in for A29's marker, set the way `execute` sets it:
    a stage raised, and this is what a failed `apply` left behind.
    """
    remote: dict[str, object] = {}
    if etsy_listing_id is not None:
        remote["etsy_listing_id"] = etsy_listing_id
    if product_id is not None:
        remote["printify_product_id"] = product_id
    lock = Lockfile.empty(tool_version="test", applied_at="2024-01-01T00:00:00").model_copy(
        update={"remote": remote, "stages_completed": ["render"] if applied else []}
    )
    if incomplete:
        lock = lock.marked_incomplete("etsy_listing")
    path = workspace_root / "listings" / name / "state.lock.json"
    lock.write(path)
    # The listing document has to look *older* than the lockfile that recorded
    # it -- `edited_since_apply` compares the two mtimes, and two files written
    # in the same tick are not reliably ordered. Ageing the listing rather than
    # post-dating the lockfile leaves "now" free for a later PATCH to land in.
    touch(workspace_root / "listings" / name / "listing.yaml", offset=-10)
    return path


class CountingEtsyListingClient(FakeEtsyListingClient):
    """The fake, plus how many batch reads it was asked for.

    The count is the assertion the listings table needs: its whole reason for
    calling `listing_states` rather than `get_listing` per row is that opening
    the page costs one round trip, and only a counter can hold that.
    """

    def __init__(self, states: dict[int, str]) -> None:
        super().__init__()
        for listing_id, state in states.items():
            self.seed_listing(listing_id, state=state)
        self.batch_calls = 0

    def listing_states(self, listing_ids: Sequence[int]) -> dict[int, str]:
        self.batch_calls += 1
        return super().listing_states(listing_ids)


EtsyStates = Callable[[dict[int, str]], CountingEtsyListingClient]


@pytest.fixture
def etsy_says(monkeypatch: pytest.MonkeyPatch) -> EtsyStates:
    """Point the status endpoints at an in-memory Etsy reporting these
    states. Patched at `connections`, which is the one place a client is
    built (see CLAUDE.md's invariant), so nothing here has to know how a
    transport is assembled."""

    def install(states: dict[int, str]) -> CountingEtsyListingClient:
        fake = CountingEtsyListingClient(states)
        monkeypatch.setattr(etsystate.connections, "etsy_listing_client", lambda _root: fake)
        return fake

    return install


def touch(path: Path, *, offset: float) -> None:
    """Move *path*'s mtime ``offset`` seconds into the future (or past)."""
    stamp = time.time() + offset
    os.utime(path, (stamp, stamp))


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
        the ``designs/take-a-hike.png`` ref stored in listing.yaml."""
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
            "on-light": "designs/take-a-hike.png",
            "on-dark": "designs/take-a-hike.png",
        }
        path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

        row = {r["name"]: r for r in client.get("/api/listings").json()}["take-a-hike"]
        assert row["design"] is None

    def test_an_applied_row_carries_the_ids_its_open_menu_links_to(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        """The table offers "Open on Etsy / Open on Printify" on a row that
        has been applied, the same menu the editor's page head has. Carried on
        the summary so the menu costs no extra request per row."""
        write_lock(workspace_root, "take-a-hike", etsy_listing_id=555, product_id="abc123")

        row = {r["name"]: r for r in client.get("/api/listings").json()}["take-a-hike"]
        assert row["etsy_listing_id"] == 555
        assert row["printify_product_id"] == "abc123"

    def test_a_draft_row_has_no_remote_ids(self, client: TestClient) -> None:
        row = {r["name"]: r for r in client.get("/api/listings").json()}["take-a-hike"]
        assert row["etsy_listing_id"] is None
        assert row["printify_product_id"] is None

    def test_blank_copy_and_an_undersized_design_both_count_as_blocking(
        self, client: TestClient
    ) -> None:
        """The fixture design (360x432) is far short of the garment's
        4500x5400 print area, and the copy is still blank -- both are
        structural non-issues (valid `Listing`) but real business blockers."""
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

    def test_design_content_change_updates_editor_identity(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        first = client.get("/api/listings/take-a-hike").json()["design_content_hash"]
        design_file = workspace_root / "designs" / "take-a-hike.png"
        design_file.write_bytes(design_file.read_bytes() + b"updated")

        second = client.get("/api/listings/take-a-hike").json()["design_content_hash"]

        assert first is not None
        assert second != first

    def test_missing_secondary_design_does_not_mask_a_primary_change(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        edit_listing(
            workspace_root,
            design={
                "default": "designs/take-a-hike.png",
                "alternate": "designs/missing.png",
            },
        )
        first = client.get("/api/listings/take-a-hike").json()["design_content_hash"]
        design_file = workspace_root / "designs" / "take-a-hike.png"
        design_file.write_bytes(design_file.read_bytes() + b"updated")

        second = client.get("/api/listings/take-a-hike").json()["design_content_hash"]

        assert first is not None
        assert second != first

    def test_profile_blueprint_context_changes_without_a_new_profile_name(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        original = client.get("/api/listings/take-a-hike").json()
        edit_garment_profile(
            workspace_root,
            "comfort-colors-1717",
            blueprint={"brand": "New Brand", "model": "2000", "title": "Long sleeve tee"},
        )

        updated = client.get("/api/listings/take-a-hike").json()

        assert updated["garment_profile"] == original["garment_profile"]
        assert updated["garment_materials"] == original["garment_materials"]
        assert updated["garment_product_type"] == "Long sleeve tee"
        assert updated["garment_brand"] == "New Brand"
        assert updated["garment_model"] == "2000"

    def test_returns_listing_yaml_modified_time(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        path = workspace_root / "listings" / "take-a-hike" / "listing.yaml"
        touch(path, offset=-3600)

        body = client.get("/api/listings/take-a-hike").json()

        expected = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        assert datetime.fromisoformat(body["modified_at"]) == expected

    def test_reports_the_blank_title_as_a_details_block(self, client: TestClient) -> None:
        issues = client.get("/api/listings/take-a-hike").json()["issues"]
        assert any(
            i["tab"] == "details" and i["severity"] == "block" and "title" in i["message"].lower()
            for i in issues
        )

    def test_reports_a_missing_common_copy_ref_as_a_details_block(self, client: TestClient) -> None:
        client.patch(
            "/api/listings/take-a-hike",
            json={"etsy": {"description": {"lead": "A retro sunset.", "ref": "common-copy/x.md"}}},
        )

        issues = client.get("/api/listings/take-a-hike").json()["issues"]

        matches = [
            i
            for i in issues
            if i["tab"] == "details"
            and i["severity"] == "block"
            and "common-copy/x.md" in i["message"]
        ]
        assert matches

    def test_a_valid_common_copy_ref_raises_no_description_issue(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        common_copy = workspace_root / "common-copy"
        common_copy.mkdir()
        (common_copy / "comfort-colors.md").write_text(
            "---\ntitle: Comfort Colors\ntargets: [description]\n---\nPrinted to order.",
            encoding="utf-8",
        )
        client.patch(
            "/api/listings/take-a-hike",
            json={
                "etsy": {
                    "description": {
                        "lead": "A retro sunset.",
                        "ref": "common-copy/comfort-colors.md",
                    }
                }
            },
        )

        issues = client.get("/api/listings/take-a-hike").json()["issues"]

        assert not any("common-copy" in i["message"] for i in issues)

    def test_composes_the_description_from_lead_and_ref_body(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        """`description_composed` is the same string every deployment reader
        gets from `Workspace.compose_description` -- the editor's own preview
        of the final copy must read it here rather than re-joining lead and
        body itself (AI SEO implementation plan, "Description and
        common-copy boundaries")."""
        common_copy = workspace_root / "common-copy"
        common_copy.mkdir()
        (common_copy / "comfort-colors.md").write_text(
            "---\ntitle: Comfort Colors\ntargets: [description]\n---\nPrinted to order.",
            encoding="utf-8",
        )
        client.patch(
            "/api/listings/take-a-hike",
            json={
                "etsy": {
                    "description": {
                        "lead": "A retro sunset.",
                        "ref": "common-copy/comfort-colors.md",
                    }
                }
            },
        )

        body = client.get("/api/listings/take-a-hike").json()

        assert body["description_composed"] == "A retro sunset.\n\nPrinted to order."

    def test_description_issue_and_preview_use_the_same_common_copy_read(
        self, client: TestClient, workspace_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        shared = workspace_root / "common-copy"
        shared.mkdir()
        copy_file = shared / "comfort-colors.md"
        copy_file.write_text(
            "---\ntitle: Comfort Colors\ntargets: [description]\n---\nPrinted to order.",
            encoding="utf-8",
        )
        client.patch(
            "/api/listings/take-a-hike",
            json={
                "etsy": {
                    "description": {
                        "lead": "A retro sunset.",
                        "ref": "common-copy/comfort-colors.md",
                    }
                }
            },
        )
        original = Workspace.load_common_copy
        reads = 0

        def read_then_remove(workspace: Workspace, ref: str):
            nonlocal reads
            reads += 1
            document = original(workspace, ref)
            copy_file.unlink()
            return document

        monkeypatch.setattr(Workspace, "load_common_copy", read_then_remove)
        body = client.get("/api/listings/take-a-hike").json()

        assert reads == 1
        assert body["description_composed"] == "A retro sunset.\n\nPrinted to order."
        assert not any("common-copy" in issue["message"] for issue in body["issues"])

    def test_composed_description_falls_back_to_the_lead_alone_for_a_bad_ref(
        self, client: TestClient
    ) -> None:
        """A `ref` that will not resolve already surfaces as a block issue
        (`test_reports_a_missing_common_copy_ref_as_a_details_block` above) --
        the composed preview must not also raise, it just cannot include a
        body it could not load."""
        client.patch(
            "/api/listings/take-a-hike",
            json={"etsy": {"description": {"lead": "A retro sunset.", "ref": "common-copy/x.md"}}},
        )

        body = client.get("/api/listings/take-a-hike").json()

        assert body["description_composed"] == "A retro sunset."

    def test_reports_the_undersized_design_as_a_variants_block(self, client: TestClient) -> None:
        issues = client.get("/api/listings/take-a-hike").json()["issues"]
        matches = [i for i in issues if i["tab"] == "variants" and i["severity"] == "block"]
        assert any("360" in i["message"] for i in matches)

    def test_reports_a_too_short_video_as_an_images_block_naming_it(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        """PRD 71's gate, read through `WorkspaceFacts` off the real file."""
        shutil.copy(
            VIDEOS / "short-2s-512.mp4", workspace_root / "listings" / "take-a-hike" / "clip.mp4"
        )
        edit_listing(
            workspace_root, media=[{"template": "flat-lay-01", "colour": "black"}, "./clip.mp4"]
        )

        issues = client.get("/api/listings/take-a-hike").json()["issues"]

        [block] = [i for i in issues if "./clip.mp4" in i["message"]]
        assert (block["severity"], block["tab"]) == ("block", "images")
        assert "3–15 seconds" in block["message"]

    def test_a_video_s_audio_is_a_note_the_table_does_not_count(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        before = next(r for r in client.get("/api/listings").json() if r["name"] == "take-a-hike")[
            "issue_counts"
        ]
        shutil.copy(
            VIDEOS / "with-audio-3s-512.mp4",
            workspace_root / "listings" / "take-a-hike" / "clip.mp4",
        )
        edit_listing(
            workspace_root, media=[{"template": "flat-lay-01", "colour": "black"}, "./clip.mp4"]
        )

        issues = client.get("/api/listings/take-a-hike").json()["issues"]
        after = next(r for r in client.get("/api/listings").json() if r["name"] == "take-a-hike")[
            "issue_counts"
        ]

        assert [i["severity"] for i in issues if "./clip.mp4" in i["message"]] == ["info"]
        assert after == before

    def test_warns_about_colours_the_garment_profile_does_not_classify(
        self, client: TestClient
    ) -> None:
        """The fixture garment profile has an empty `colors:` dict, so every
        one of the listing's four colours is an unclassified proxy-warning."""
        issues = client.get("/api/listings/take-a-hike").json()["issues"]
        warning = next(i for i in issues if i["tab"] == "variants" and i["severity"] == "warn")
        assert all(c in warning["message"] for c in ["black", "blue-jean", "ivory", "moss"])

    def test_an_applied_listing_carries_its_remote_ids(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        write_lock(workspace_root, "take-a-hike", etsy_listing_id=555, product_id="abc123")

        body = client.get("/api/listings/take-a-hike").json()
        assert body["status"] == "deployed"
        assert body["etsy_listing_id"] == 555
        assert body["printify_product_id"] == "abc123"


class TestListingStatus:
    """The four-state lifecycle (`engine/status.py`), end to end through the
    API -- which is where the two local facts (has it been applied, has it
    been edited since) meet the remote one (has Etsy published it).

    Every test here runs with no Etsy credentials except the ones that
    deliberately fake a client, so "live" is never guessed at: a workspace
    that cannot ask reports every listing as not-live.
    """

    def status(self, client: TestClient, name: str = "take-a-hike") -> str:
        body: str = client.get(f"/api/listings/{name}").json()["status"]
        return body

    def test_a_listing_that_has_never_been_applied_is_a_draft(self, client: TestClient) -> None:
        assert self.status(client) == "draft"

    def test_an_applied_listing_is_deployed(self, client: TestClient, workspace_root: Path) -> None:
        write_lock(workspace_root, "take-a-hike", etsy_listing_id=555)
        assert self.status(client) == "deployed"

    def test_a_lockfile_with_no_stage_completed_is_still_a_draft(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        """A lockfile carrying ids but no completed stage is not evidence of
        an apply -- and `deployed` claims one happened."""
        write_lock(workspace_root, "take-a-hike", etsy_listing_id=555, applied=False)
        assert self.status(client) == "draft"

    def test_editing_a_deployed_listing_takes_it_back_to_draft(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        write_lock(workspace_root, "take-a-hike", etsy_listing_id=555)
        client.patch("/api/listings/take-a-hike", json={"brief": "a new brief"})
        assert self.status(client) == "draft"

    def test_a_published_listing_is_live(
        self, client: TestClient, workspace_root: Path, etsy_says: EtsyStates
    ) -> None:
        write_lock(workspace_root, "take-a-hike", etsy_listing_id=555)
        etsy_says({555: "active"})
        assert self.status(client) == "live"

    def test_editing_a_live_listing_makes_it_dirty(
        self, client: TestClient, workspace_root: Path, etsy_says: EtsyStates
    ) -> None:
        """The asymmetry worth having: the same edit that sends a `deployed`
        listing back to `draft` sends a live one to `dirty`, because a buyer
        is looking at the stale copy."""
        write_lock(workspace_root, "take-a-hike", etsy_listing_id=555)
        etsy_says({555: "active"})
        client.patch("/api/listings/take-a-hike", json={"brief": "a new brief"})
        assert self.status(client) == "dirty"

    def test_a_partially_applied_live_listing_reads_dirty_not_live(
        self, client: TestClient, workspace_root: Path, etsy_says: EtsyStates
    ) -> None:
        """A29: a failed `apply` leaves the marker set, and the per-stage
        write already made the lockfile newer than the yaml -- so nothing
        about mtimes tells the API this listing's Etsy copy might not match
        what was reviewed. Without wiring the marker through, this would
        read `live` and hide exactly the case the marker exists to catch."""
        write_lock(workspace_root, "take-a-hike", etsy_listing_id=555, incomplete=True)
        etsy_says({555: "active"})
        assert self.status(client) == "dirty"

    def test_a_listing_etsy_still_calls_a_draft_is_deployed(
        self, client: TestClient, workspace_root: Path, etsy_says: EtsyStates
    ) -> None:
        """What `deployed` is *for*: the pipeline never activates a listing
        (PRD non-goal 1), so an applied listing sits at Etsy as a draft until
        a human publishes it."""
        write_lock(workspace_root, "take-a-hike", etsy_listing_id=555)
        etsy_says({555: "draft"})
        assert self.status(client) == "deployed"

    def test_a_sold_out_listing_counts_as_live(
        self, client: TestClient, workspace_root: Path, etsy_says: EtsyStates
    ) -> None:
        """`sold_out` is a published listing in a particular condition, not an
        unpublished one -- reading it as not-live would report a listing
        buyers have seen as though it had never left the workspace."""
        write_lock(workspace_root, "take-a-hike", etsy_listing_id=555)
        etsy_says({555: "sold_out"})
        assert self.status(client) == "live"

    def test_the_table_asks_etsy_once_for_every_row(
        self, client: TestClient, workspace_root: Path, etsy_says: EtsyStates
    ) -> None:
        """One batch read for the whole table, not one `getListing` per row --
        the reason `listing_states` exists."""
        write_lock(workspace_root, "take-a-hike", etsy_listing_id=555)
        fake = etsy_says({555: "active"})

        rows = {r["name"]: r for r in client.get("/api/listings").json()}

        assert rows["take-a-hike"]["status"] == "live"
        assert fake.batch_calls == 1

    def test_the_table_reads_the_template_catalogue_once_for_every_row(
        self, client: TestClient, workspace_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The Etsy rule above, applied to the workspace.

        Every row's issue check needs each template's real kind and colours,
        and each row used to re-list and re-parse the whole catalogue to get
        them -- twenty listings over twenty templates parsed four hundred
        ``template.yaml`` files per paint. `WorkspaceFacts` gathers them once
        for the request, so no template is parsed twice however many rows the
        table has.
        """
        copy_listing(workspace_root, "second-listing")
        parsed: list[str] = []
        real = Workspace.load_template_config

        def counting(self: Workspace, template: str) -> object:
            parsed.append(template)
            return real(self, template)

        monkeypatch.setattr(Workspace, "load_template_config", counting)

        rows = client.get("/api/listings").json()

        assert {r["name"] for r in rows} == {"take-a-hike", "second-listing"}
        assert parsed, "the check really does read the catalogue"
        assert sorted(parsed) == sorted(set(parsed)), f"a template parsed twice: {parsed}"

    def test_a_workspace_with_no_etsy_credentials_still_lists(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        """No key pair is an ordinary state short of Phase 3. The page opens,
        and nothing is reported as live."""
        write_lock(workspace_root, "take-a-hike", etsy_listing_id=555)
        rows = client.get("/api/listings").json()
        assert [r["status"] for r in rows if r["name"] == "take-a-hike"] == ["deployed"]


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

    def test_detail_reports_materials_from_the_garment_profile(self, client: TestClient) -> None:
        """A listing does not own materials, but still tells the editor what
        the selected garment will send to Etsy."""
        response = client.patch(
            "/api/listings/take-a-hike", json={"etsy": {"title": "Take A Hike Tee"}}
        )
        assert response.json()["garment_materials"] == ["cotton"]

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
    """Naming a listing is what creates it, and the document sent is the one
    written -- there is no server-built stub any more. The contract mirrors
    PATCH: a document that will not validate is a 200 carrying `field_errors`
    with nothing written, and only a *name* gets a status code."""

    def _document(self, **over: object) -> dict[str, object]:
        document: dict[str, object] = {
            "garment_profile": "comfort-colors-1717",
            "design": "designs/take-a-hike.png",
            "colors": ["black"],
            "brief": "",
            "prices": {"S": "349 NOK"},
            "media": [],
        }
        document.update(over)
        return document

    def test_writes_the_document_it_was_given_and_returns_it(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        response = client.post(
            "/api/listings", json={"name": "my-new-shirt", "document": self._document()}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "my-new-shirt"
        assert body["design"] == {"default": "designs/take-a-hike.png"}
        assert body["colors"] == ["black"]

        written = workspace_root / "listings" / "my-new-shirt" / "listing.yaml"
        assert written.is_file()
        assert yaml.safe_load(written.read_text(encoding="utf-8"))["colors"] == ["black"]

    def test_does_not_need_a_pricing_plan_to_exist(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        """The fixture workspace has no `pricing-plans/` at all, and used to be
        unable to create a listing at all because of it -- which made the UI
        that exists to create a workspace's first listing the one thing a fresh
        workspace could not do."""
        assert not (workspace_root / "pricing-plans").exists()
        response = client.post(
            "/api/listings", json={"name": "priced-by-hand", "document": self._document()}
        )
        assert response.status_code == 200
        assert (workspace_root / "listings" / "priced-by-hand" / "listing.yaml").is_file()

    def test_an_incomplete_document_is_written_and_its_gaps_reported(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        """PRD 70: naming writes it. No price source is an incompleteness, not
        a malformed document, so the file appears and the banner carries the
        block issue that stops a deploy.

        This test used to assert the opposite, and it was the one rule out of
        eight that behaved that way -- a seller with a named listing, a design
        and colours watched the tool decline to save their work."""
        response = client.post(
            "/api/listings",
            json={"name": "half-done", "document": self._document(prices={}, pricing_plan=None)},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "half-done"
        assert any(i["where"] == "Pricing" and i["severity"] == "block" for i in body["issues"])
        assert (workspace_root / "listings" / "half-done" / "listing.yaml").is_file()

    def test_a_structurally_broken_document_comes_back_as_field_errors(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        """A bare number is not a price (PRD 24) -- that one *is* a field error,
        rendered inline, and still writes nothing.

        The other side of PRD 70's line: incomplete is written, malformed is
        not."""
        response = client.post(
            "/api/listings",
            json={"name": "bad-money", "document": self._document(prices={"S": 349})},
        )
        assert response.status_code == 200
        assert response.json()["field_errors"] != {}
        assert not (workspace_root / "listings" / "bad-money").exists()

    def test_conflicts_with_an_existing_listing_name(self, client: TestClient) -> None:
        response = client.post(
            "/api/listings", json={"name": "take-a-hike", "document": self._document()}
        )
        assert response.status_code == 409

    def test_conflicts_with_a_directory_that_has_no_listing_file(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        """A `listings/<name>/` left behind with a lockfile and no document.
        Writing into it would hand the new listing the old one's remote ids."""
        leftover = workspace_root / "listings" / "half-deleted"
        leftover.mkdir(parents=True)
        (leftover / "state.lock.json").write_text("{}", encoding="utf-8")

        response = client.post(
            "/api/listings", json={"name": "half-deleted", "document": self._document()}
        )
        assert response.status_code == 409

    def test_refuses_a_name_that_is_not_a_path_segment(self, client: TestClient) -> None:
        response = client.post(
            "/api/listings", json={"name": "../escape", "document": self._document()}
        )
        assert response.status_code == 400


class TestListingDraft:
    def test_the_draft_has_nothing_chosen(self, client: TestClient) -> None:
        response = client.get("/api/listing-draft")
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == ""
        assert body["status"] == "draft"
        assert body["garment_profile"] == ""
        assert body["design"] == {}
        assert body["colors"] == []
        assert body["pricing_plan"] is None
        assert body["media"] == []
        assert body["etsy"]["title"] == ""
        assert body["etsy"]["description"] == {"lead": "", "text": None, "ref": None}

    def test_the_draft_opens_in_a_workspace_with_no_pricing_plan(self, client: TestClient) -> None:
        """It used to 400 here, which showed "could not start a new listing"
        forever in exactly the workspace that has never made one."""
        assert client.get("/api/listing-draft").status_code == 200

    def test_the_draft_blocks_on_each_thing_still_to_pick(self, client: TestClient) -> None:
        blocks = {
            i["where"]
            for i in client.get("/api/listing-draft").json()["issues"]
            if i["severity"] == "block"
        }
        assert "Variants › Garment profile" in blocks
        assert "Design" in blocks
        assert "Variants › Colours" in blocks
        assert "Pricing" in blocks
        assert "Listing Images" in blocks

    def test_the_draft_writes_nothing(self, client: TestClient, workspace_root: Path) -> None:
        before = sorted(p.name for p in (workspace_root / "listings").iterdir())
        client.get("/api/listing-draft")
        assert sorted(p.name for p in (workspace_root / "listings").iterdir()) == before

    def test_describing_a_candidate_recomputes_its_issues(self, client: TestClient) -> None:
        """What keeps the banner true while the listing has no name: pick
        colours and the "no colours" block has to go away, or the only channel
        an unsaved listing has for being told what it needs is lying to it."""
        document = {
            "garment_profile": "comfort-colors-1717",
            "design": "designs/take-a-hike.png",
            "colors": ["black"],
            "brief": "",
            "media": [],
        }
        body = client.post("/api/listing-draft", json={"document": document}).json()
        wheres = {i["where"] for i in body["issues"] if i["severity"] == "block"}
        assert "Variants › Colours" not in wheres
        assert "Variants › Garment profile" not in wheres
        assert "Pricing" in wheres

    def test_describing_a_candidate_writes_nothing(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        before = sorted(p.name for p in (workspace_root / "listings").iterdir())
        client.post(
            "/api/listing-draft",
            json={"document": {"garment_profile": "comfort-colors-1717", "colors": ["black"]}},
        )
        assert sorted(p.name for p in (workspace_root / "listings").iterdir()) == before

    def test_a_structurally_broken_candidate_comes_back_as_field_errors(
        self, client: TestClient
    ) -> None:
        """A bare number is not a price (PRD 24). The draft cannot be described
        as a `Listing` at all then, so the errors are the news and the rest of
        the body describes the empty draft -- which is why the editor keeps its
        own state for everything but `field_errors`."""
        body = client.post(
            "/api/listing-draft",
            json={
                "document": {
                    "garment_profile": "comfort-colors-1717",
                    "design": "designs/take-a-hike.png",
                    "colors": ["black"],
                    "brief": "",
                    "media": [],
                    "prices": {"S": 349},
                }
            },
        ).json()
        assert body["field_errors"] != {}

    def test_an_unusable_garment_profile_is_an_issue_not_a_400(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        """`""` reaches `_segment`, which refuses it -- and a refusal there
        used to take the whole editor down rather than filling in one line of
        its banner."""
        listing = workspace_root / "listings" / "take-a-hike" / "listing.yaml"
        document = yaml.safe_load(listing.read_text(encoding="utf-8"))
        document["garment_profile"] = ""
        listing.write_text(yaml.safe_dump(document), encoding="utf-8")

        response = client.get("/api/listings/take-a-hike")
        assert response.status_code == 200
        assert any(
            i["where"] == "Variants › Garment profile" and i["severity"] == "block"
            for i in response.json()["issues"]
        )


class TestRenameListing:
    def test_moves_the_directory_and_its_lockfile(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        write_lock(workspace_root, "take-a-hike", etsy_listing_id=12345, product_id="prod-1")

        response = client.post("/api/listings/take-a-hike/rename", json={"new_name": "hike-away"})
        assert response.status_code == 200
        assert response.json()["name"] == "hike-away"
        # The ids came from the lockfile, so reading them back proves it moved.
        assert response.json()["etsy_listing_id"] == 12345

        assert not (workspace_root / "listings" / "take-a-hike").exists()
        assert (workspace_root / "listings" / "hike-away" / "listing.yaml").is_file()
        assert (workspace_root / "listings" / "hike-away" / "state.lock.json").is_file()

    def test_moves_the_render_cache(self, client: TestClient, workspace_root: Path) -> None:
        """The cache is keyed by listing name. Left behind it would orphan a
        tree nothing deletes, and cost a full re-render of a listing nothing
        about which changed."""
        cached = workspace_root / ".cache" / "renders" / "take-a-hike" / "flat-lay-01"
        cached.mkdir(parents=True)
        (cached / "black.png").write_bytes(b"not really a png")

        assert (
            client.post(
                "/api/listings/take-a-hike/rename", json={"new_name": "hike-away"}
            ).status_code
            == 200
        )

        assert not (workspace_root / ".cache" / "renders" / "take-a-hike").exists()
        moved = workspace_root / ".cache" / "renders" / "hike-away" / "flat-lay-01" / "black.png"
        assert moved.read_bytes() == b"not really a png"

    def test_renaming_to_the_same_name_changes_nothing(self, client: TestClient) -> None:
        """Blur commits an unchanged name constantly; that is not a conflict."""
        response = client.post("/api/listings/take-a-hike/rename", json={"new_name": "take-a-hike"})
        assert response.status_code == 200
        assert response.json()["name"] == "take-a-hike"

    def test_refuses_a_name_already_in_use(self, client: TestClient, workspace_root: Path) -> None:
        (workspace_root / "listings" / "taken").mkdir(parents=True)
        response = client.post("/api/listings/take-a-hike/rename", json={"new_name": "taken"})
        assert response.status_code == 409
        assert (workspace_root / "listings" / "take-a-hike").is_dir()

    def test_refuses_a_name_that_is_not_a_path_segment(self, client: TestClient) -> None:
        response = client.post(
            "/api/listings/take-a-hike/rename", json={"new_name": "../elsewhere"}
        )
        assert response.status_code == 400

    def test_unknown_listing_is_a_404(self, client: TestClient) -> None:
        response = client.post("/api/listings/no-such/rename", json={"new_name": "whatever"})
        assert response.status_code == 404


class TestSupportingEndpoints:
    def test_lists_garment_profiles(self, client: TestClient) -> None:
        response = client.get("/api/garment-profiles")
        assert response.status_code == 200
        by_name = {row["name"]: row for row in response.json()}
        assert by_name["comfort-colors-1717"]["sizes"] == ["S", "M", "L", "XL", "XXL", "XXXL"]
        # The Variants tab's colour preview is this template, not the first
        # colour-matrix in media: (A13). The fixture names the workspace's
        # colour-matrix set.
        assert by_name["comfort-colors-1717"]["preview_template"] == "flat-lay-01"

    def test_a_garment_profile_without_preview_template_reports_null(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        """Existing files omit the field; the editor treats null as 'no preview'
        rather than guessing a template from media:."""
        edit_garment_profile(workspace_root, "comfort-colors-1717", preview_template=None)
        response = client.get("/api/garment-profiles")
        assert response.status_code == 200
        by_name = {row["name"]: row for row in response.json()}
        assert by_name["comfort-colors-1717"]["preview_template"] is None

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
        # `ref` is what a PATCH writes straight into `pricing_plan:` --
        # workspace-rooted (PRD 72), ready to use unchanged (mirrors
        # `CommonMediaSummary.ref`).
        assert by_name["tee-basic"]["ref"] == "pricing-plans/tee-basic.yaml"

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
            # RGBA, not RGB: flattening onto RGB bakes a transparent
            # background to opaque black instead of leaving it transparent
            # for the row/hover-card tile's own CSS background to show
            # through.
            assert img.mode == "RGBA"

    def test_a_design_thumbnail_404s_for_an_unknown_design(self, client: TestClient) -> None:
        assert client.get("/api/listing-designs/no-such-art/thumbnail").status_code == 404

    def test_lists_common_media_with_the_ref_a_listing_stores(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        """The picker hands back the ref ready to write. A shared file's ref is
        its workspace-relative path (PRD 72), with no `../../` in front."""
        shared = workspace_root / "common-media"
        shared.mkdir(exist_ok=True)
        (shared / "size-guide.png").write_bytes(b"")

        response = client.get("/api/common-media")
        assert response.status_code == 200
        by_name = {row["name"]: row for row in response.json()}
        assert by_name["size-guide"]["ref"] == "common-media/size-guide.png"
        assert by_name["size-guide"]["file"] == "common-media/size-guide.png"

    def test_common_media_is_empty_on_a_workspace_that_has_none(self, client: TestClient) -> None:
        assert client.get("/api/common-media").json() == []

    def test_serves_a_common_media_thumbnail(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        shared = workspace_root / "common-media"
        shared.mkdir(exist_ok=True)
        Image.new("RGB", (900, 700), (210, 180, 140)).save(shared / "size-guide.png")

        response = client.get("/api/common-media/size-guide/thumbnail")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        with Image.open(BytesIO(response.content)) as img:
            assert max(img.size) <= 160

    def test_a_common_media_thumbnail_404s_for_an_unknown_asset(self, client: TestClient) -> None:
        assert client.get("/api/common-media/no-such-asset/thumbnail").status_code == 404

    def test_serves_a_common_media_file_at_its_own_size(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        """The other half of the pair: the thumbnail is a picture to *pick*
        out of a list, this is the one the editor's preview pane and its
        lightbox show -- and it is the file Etsy would actually receive,
        byte for byte, not a re-encode."""
        shared = workspace_root / "common-media"
        shared.mkdir(exist_ok=True)
        source = shared / "size-guide.png"
        Image.new("RGB", (900, 700), (210, 180, 140)).save(source)

        response = client.get("/api/common-media/size-guide/file")
        assert response.status_code == 200
        assert response.content == source.read_bytes()

    def test_a_common_media_file_404s_for_an_unknown_asset(self, client: TestClient) -> None:
        assert client.get("/api/common-media/no-such-asset/file").status_code == 404

    def test_lists_common_copy_files_with_their_front_matter(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        """The Description tab's common-copy selector (AI SEO implementation
        plan, PR6) needs titles and summaries to show, not just filenames --
        so the listing endpoint parses each file's front matter rather than
        handing back a bare directory listing."""
        shared = workspace_root / "common-copy"
        shared.mkdir(exist_ok=True)
        (shared / "comfort-colors.md").write_text(
            "---\ntitle: Comfort Colors care and fit\ntargets: [description]\n"
            "summary: Care and fit notes.\n---\nPrinted to order.",
            encoding="utf-8",
        )

        response = client.get("/api/common-copy")
        assert response.status_code == 200
        [row] = response.json()
        assert row["ref"] == "common-copy/comfort-colors.md"
        assert row["title"] == "Comfort Colors care and fit"
        assert row["summary"] == "Care and fit notes."

    def test_common_copy_is_empty_on_a_workspace_that_has_none(self, client: TestClient) -> None:
        assert client.get("/api/common-copy").json() == []

    def test_common_copy_omits_a_file_whose_front_matter_will_not_parse(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        """A malformed file cannot be selected -- offering it in the list
        would only produce a pick that immediately fails, so it is left out
        rather than shown broken. (The banner already tells a seller about a
        *stored* ref that fails to resolve; this is the picker's own list.)"""
        shared = workspace_root / "common-copy"
        shared.mkdir(exist_ok=True)
        (shared / "broken.md").write_text("not front matter at all", encoding="utf-8")

        assert client.get("/api/common-copy").json() == []

    def test_names_the_shop_the_sidebar_says_you_are_working_on(self, client: TestClient) -> None:
        """One workspace per shop, so the sidebar says which -- the difference
        between a test shop and the real one is worth seeing before an edit,
        not after an apply."""
        response = client.get("/api/workspace")
        assert response.status_code == 200
        assert response.json()["shop_name"] == "TakeAHikeTees"

    def test_storage_identity_distinguishes_workspaces_with_the_same_shop_name(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        other_root = workspace_root.parent / "other-workspace"
        other_root.mkdir()
        shutil.copyfile(workspace_root / "shop.yaml", other_root / "shop.yaml")
        with TestClient(create_app(Workspace.discover(root_override=other_root))) as other:
            other_summary = other.get("/api/workspace").json()

        summary = client.get("/api/workspace").json()
        assert summary["shop_name"] == other_summary["shop_name"]
        assert summary["storage_id"] != other_summary["storage_id"]

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


class TestEtsySections:
    """`GET /api/etsy/sections`: the Details tab's Section dropdown, backed
    by `EtsyShopClient.shop_sections` -- unscoped, so this needs only the
    workspace's app key pair, never a signed-in Etsy session."""

    def test_is_empty_without_a_shop_id(self, client: TestClient) -> None:
        """The fixture workspace deliberately carries no `etsy.shop_id`."""
        response = client.get("/api/etsy/sections")
        assert response.status_code == 200
        assert response.json() == []

    def test_is_empty_with_a_shop_id_but_no_app_key_pair(self, workspace_root: Path) -> None:
        set_etsy_shop_id(workspace_root, 12345678)
        keyless = TestClient(create_app(Workspace.discover(root_override=workspace_root)))
        response = keyless.get("/api/etsy/sections")
        assert response.status_code == 200
        assert response.json() == []

    def test_lists_the_live_shops_sections(
        self, workspace_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        set_etsy_shop_id(workspace_root, 12345678)
        monkeypatch.setattr(
            connections,
            "etsy_shop_client",
            lambda root: FakeEtsyShopClient(
                sections=[
                    ShopSection(shop_section_id=1, title="Tees"),
                    ShopSection(shop_section_id=2, title="Hoodies"),
                ]
            ),
        )
        sectioned = TestClient(create_app(Workspace.discover(root_override=workspace_root)))
        response = sectioned.get("/api/etsy/sections")
        assert response.status_code == 200
        assert response.json() == [
            {"id": 1, "title": "Tees"},
            {"id": 2, "title": "Hoodies"},
        ]


class TestLifecycle:
    def _row(self, client: TestClient, name: str = "take-a-hike") -> dict:
        rows = {r["name"]: r for r in client.get("/api/listings").json()}
        return rows[name]

    def test_a_never_live_row_offers_delete(self, client: TestClient) -> None:
        assert self._row(client)["gestures"] == ["delete"]

    def test_a_live_row_offers_retire(
        self, client: TestClient, workspace_root: Path, etsy_says: EtsyStates
    ) -> None:
        write_lock(workspace_root, "take-a-hike", etsy_listing_id=555)
        etsy_says({555: "active"})
        assert self._row(client)["gestures"] == ["retire"]
        assert self._row(client)["status"] == "live"

    def test_etsy_paused_us_offers_retire_and_renew(
        self, client: TestClient, workspace_root: Path, etsy_says: EtsyStates
    ) -> None:
        write_lock(workspace_root, "take-a-hike", etsy_listing_id=555)
        etsy_says({555: "inactive"})
        assert self._row(client)["gestures"] == ["retire", "renew"]
        assert self._row(client)["status"] == "inactive"

    def test_expired_is_named(
        self, client: TestClient, workspace_root: Path, etsy_says: EtsyStates
    ) -> None:
        write_lock(workspace_root, "take-a-hike", etsy_listing_id=555)
        etsy_says({555: "expired"})
        assert self._row(client)["status"] == "expired"

    def test_patch_writes_retired_and_un_retire_deletes_the_key(
        self, client: TestClient, workspace_root: Path, etsy_says: EtsyStates
    ) -> None:
        write_lock(workspace_root, "take-a-hike", etsy_listing_id=555)
        etsy_says({555: "active"})
        client.patch("/api/listings/take-a-hike", json={"lifecycle": "retired"})
        assert self._row(client)["gestures"] == ["un-retire"]
        assert self._row(client)["status"] == "pending-retire"
        client.patch("/api/listings/take-a-hike", json={"lifecycle": None})
        written = yaml.safe_load(listing_file(workspace_root).read_text(encoding="utf-8"))
        assert "lifecycle" not in written
        assert self._row(client)["gestures"] == ["retire"]

    def test_delete_without_remotes_wipes_now(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        response = client.delete("/api/listings/take-a-hike")
        assert response.status_code == 204
        assert not (workspace_root / "listings" / "take-a-hike").exists()

    def test_delete_with_remotes_marks_pending_delete(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        write_lock(workspace_root, "take-a-hike", product_id="abc123")
        response = client.delete("/api/listings/take-a-hike")
        assert response.status_code == 200
        assert response.json()["status"] == "pending-delete"
        assert response.json()["gestures"] == ["cancel"]
        written = yaml.safe_load(listing_file(workspace_root).read_text(encoding="utf-8"))
        assert written["lifecycle"] == "deleted"

    def test_delete_of_a_published_listing_is_refused(
        self, client: TestClient, workspace_root: Path, etsy_says: EtsyStates
    ) -> None:
        write_lock(workspace_root, "take-a-hike", etsy_listing_id=555)
        etsy_says({555: "active"})
        response = client.delete("/api/listings/take-a-hike")
        assert response.status_code == 409
        assert "published" in response.json()["detail"]

    def test_a_lockfile_only_row_still_appears(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        write_lock(workspace_root, "take-a-hike", etsy_listing_id=555)
        listing_file(workspace_root).unlink()
        row = self._row(client)
        assert row["issue_counts"]["block"] == 1
        assert row["gestures"] == []
