"""Reading, editing, renaming and deleting a listing, called directly -- no
``TestClient``, no ``CliRunner`` (module-structure plan, PR 6).

Each operation owns its coordination: it takes the listing's write lock
around the read-merge-write or the name check and move, re-checks the listing
is still there once it holds it, and carries the files and records that
follow a listing -- render cache, market snapshot, AI proposal, batch rows,
the AI run -- with it. What an outcome becomes on the wire (404, 409, a 200
with ``field_errors``) is the listings API tests' business.

Competing writes are made to overlap by slowing the step every listing write
passes through (``yaml.safe_dump``) or the directory move (``Path.replace``),
so the interleaving is not left to chance.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
import yaml

from etsy_listings.core.application.ai.registry import AiRunRegistry
from etsy_listings.core.application.listing_creation import create_listing
from etsy_listings.core.application.listing_edits import edit_listing
from etsy_listings.core.application.listing_identity import delete_listing, rename_listing
from etsy_listings.core.application.listing_reads import (
    describe_draft,
    list_listings,
    read_listing,
)
from etsy_listings.core.application.refusals import (
    InvalidListing,
    ListingMissing,
    ListingNameTaken,
    PublishedListingDeletion,
)
from etsy_listings.core.batches import BatchStore
from etsy_listings.core.config.listing import EMPTY_DRAFT
from etsy_listings.core.workspace.workspace import InvalidNameError, Workspace

from tests.support.ai_runs import has_proposal, seed_proposal, seed_snapshot
from tests.support.builders import FIXTURE_LISTING
from tests.support.builders import edit_listing as edit_listing_file
from tests.support.listings import (
    ai_run,
    applied,
    batch_naming,
    batch_rows,
    etsy_reports,
)

NAME = FIXTURE_LISTING


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


def _document(workspace: Workspace, name: str = NAME) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(
        workspace.listing_file(name).read_text(encoding="utf-8")
    )
    return loaded


def _edit(workspace: Workspace, patch: dict[str, Any], **kwargs: Any) -> InvalidListing | None:  # noqa: ANN401
    return edit_listing(
        workspace,
        kwargs.pop("name", NAME),
        patch,
        batches=BatchStore(workspace),
    )


def _rename(workspace: Workspace, new: str, **kwargs: Any) -> None:  # noqa: ANN401
    rename_listing(
        workspace,
        kwargs.pop("old", NAME),
        new,
        batches=BatchStore(workspace),
        ai_runs=kwargs.pop("ai_runs", AiRunRegistry()),
    )


def _delete(workspace: Workspace, **kwargs: Any):  # noqa: ANN202, ANN401
    return delete_listing(
        workspace,
        kwargs.pop("name", NAME),
        batches=BatchStore(workspace),
        ai_runs=kwargs.pop("ai_runs", AiRunRegistry()),
        etsy_states=kwargs.pop("etsy_states", etsy_reports()),
    )


# ------------------------------------------------------------------ reads


class TestReadListing:
    def test_describes_the_listing_on_disk(self, workspace: Workspace) -> None:
        view = read_listing(workspace, NAME, etsy_states=etsy_reports())

        assert view.name == NAME
        assert view.listing.colors == ["black", "blue-jean", "ivory", "moss"]
        assert view.status == "draft"
        assert view.gestures == ("delete",)
        assert view.field_errors == {}
        assert view.modified_at is not None
        assert view.garment_profile is not None
        assert view.design_content_hash is not None

    def test_carries_the_shared_completeness_issues(self, workspace: Workspace) -> None:
        """Blank copy is a business blocker, from `check_listing` itself."""
        view = read_listing(workspace, NAME, etsy_states=etsy_reports())

        assert any(
            i.tab == "details" and i.severity == "block" and "title" in i.message.lower()
            for i in view.issues
        )

    def test_a_missing_listing_is_refused(self, workspace: Workspace) -> None:
        with pytest.raises(ListingMissing):
            read_listing(workspace, "does-not-exist", etsy_states=etsy_reports())

    def test_asks_etsy_about_a_published_listing(self, workspace: Workspace) -> None:
        applied(workspace, etsy_listing_id=555)

        view = read_listing(workspace, NAME, etsy_states=etsy_reports({555: "active"}))

        assert (view.status, view.gestures) == ("live", ("retire",))
        assert view.etsy_listing_id == 555

    def test_resolves_prices_from_the_listing(self, workspace: Workspace) -> None:
        view = read_listing(workspace, NAME, etsy_states=etsy_reports())

        assert view.resolved_prices
        assert {price.size for price in view.resolved_prices} <= set(view.listing.prices)


class TestDescribeDraft:
    def test_the_empty_draft_blocks_on_each_thing_still_to_pick(self, workspace: Workspace) -> None:
        view = describe_draft(workspace, EMPTY_DRAFT)

        blocks = {i.where for i in view.issues if i.severity == "block"}
        assert {"Artwork", "Pricing", "Variants › Colours"} <= blocks
        assert (view.name, view.status, view.gestures) == ("", "draft", ())

    def test_an_incomplete_candidate_is_described_as_it_stands(self, workspace: Workspace) -> None:
        view = describe_draft(
            workspace,
            {
                "garment_profile": "comfort-colors-1717",
                "design": "designs/take-a-hike.png",
                "colors": ["black"],
                "brief": "",
                "media": [],
            },
        )

        assert view.field_errors == {}
        assert view.listing.colors == ["black"]
        blocks = {i.where for i in view.issues if i.severity == "block"}
        assert "Variants › Colours" not in blocks
        assert "Pricing" in blocks

    def test_a_malformed_candidate_answers_field_errors_over_the_empty_draft(
        self, workspace: Workspace
    ) -> None:
        """Incomplete is described; malformed is not (ADR-0043), so there is
        nothing but the empty draft to describe beside the errors."""
        view = describe_draft(workspace, {"colors": ["black"], "prices": {"S": 349}})

        assert view.field_errors
        assert view.listing.colors == []

    def test_writes_nothing(self, workspace: Workspace) -> None:
        before = sorted(p.name for p in (workspace.root / "listings").iterdir())

        describe_draft(workspace, {"colors": ["black"]})

        assert sorted(p.name for p in (workspace.root / "listings").iterdir()) == before


class TestListListings:
    def test_asks_etsy_once_for_every_row(self, workspace: Workspace) -> None:
        applied(workspace, etsy_listing_id=555)
        asked: list[list[int]] = []
        etsy = etsy_reports({555: "active"})

        def counting(ids: Any) -> Any:  # noqa: ANN401
            asked.append(list(ids))
            return etsy(ids)

        rows = list_listings(workspace, etsy_states=counting)

        assert [(r.name, r.status) for r in rows] == [(NAME, "live")]
        assert asked == [[555]]

    def test_a_lockfile_only_row_is_one_block_and_no_gestures(self, workspace: Workspace) -> None:
        applied(workspace, etsy_listing_id=555)
        workspace.listing_file(NAME).unlink()

        [row] = list_listings(workspace, etsy_states=etsy_reports())

        assert row.listing is None
        assert [i.severity for i in row.issues] == ["block"]
        assert row.gestures == ()


# ------------------------------------------------------------------ edits


class TestEditListing:
    def test_merges_a_slice_of_etsy_over_its_siblings(self, workspace: Workspace) -> None:
        """Each editor tab owns a slice of ``etsy:``; one tab's autosave must
        not erase what another wrote."""
        _edit(workspace, {"etsy": {"title": "Take A Hike Tee"}})
        _edit(workspace, {"etsy": {"tags": ["hiking"]}})

        written = _document(workspace)
        assert written["etsy"]["title"] == "Take A Hike Tee"
        assert written["etsy"]["tags"] == ["hiking"]

    def test_an_incomplete_edit_is_written(self, workspace: Workspace) -> None:
        """ADR-0043: clearing the colours and images leaves an incomplete
        listing, which is still the seller's to save."""
        assert _edit(workspace, {"colors": [], "media": []}) is None
        assert (_document(workspace)["colors"], _document(workspace)["media"]) == ([], [])

    def test_a_malformed_edit_answers_field_errors_and_writes_nothing(
        self, workspace: Workspace
    ) -> None:
        before = workspace.listing_file(NAME).read_bytes()

        refused = _edit(workspace, {"prices": {"S": "not-a-price"}})

        assert isinstance(refused, InvalidListing)
        assert any(key.startswith("prices") for key in refused.field_errors)
        assert workspace.listing_file(NAME).read_bytes() == before

    def test_a_null_lifecycle_removes_the_key(self, workspace: Workspace) -> None:
        """Un-retire and Cancel delete the key rather than writing ``active``."""
        _edit(workspace, {"lifecycle": "retired"})
        assert _document(workspace)["lifecycle"] == "retired"

        _edit(workspace, {"lifecycle": None})

        assert "lifecycle" not in _document(workspace)

    def test_a_missing_listing_is_refused(self, workspace: Workspace) -> None:
        with pytest.raises(ListingMissing):
            _edit(workspace, {"brief": "x"}, name="does-not-exist")

        assert not workspace.listing_dir("does-not-exist").exists()

    def test_cancelling_a_pending_delete_brings_its_batch_rows_back(
        self, workspace: Workspace
    ) -> None:
        """Rename and delete hooks: the listing never went, so the rows the
        delete marked return -- only once the lifecycle actually changes."""
        # As batch creation writes it: the design keyed, the form
        # `BatchStore.restore_listing` matches a row's design against.
        edit_listing_file(workspace.root, design={"default": "designs/take-a-hike.png"})
        applied(workspace, product_id="abc123")
        store = batch_naming(workspace, "b1", NAME)
        _delete(workspace)
        assert batch_rows(store, "b1")[0].deleted

        _edit(workspace, {"brief": "Still pending."})
        assert batch_rows(store, "b1")[0].deleted

        _edit(workspace, {"lifecycle": None})
        assert not batch_rows(store, "b1")[0].deleted


# ---------------------------------------------------------------- rename


class TestRenameListing:
    def test_moves_everything_keyed_by_the_listings_name(self, workspace: Workspace) -> None:
        applied(workspace, etsy_listing_id=12345)
        renders = workspace.renders_dir(NAME) / "flat-lay-01"
        renders.mkdir(parents=True)
        (renders / "black.png").write_bytes(b"not really a png")
        preview = workspace.preview_file(NAME, "flat-lay-01", "black", "deadbeef")
        preview.parent.mkdir(parents=True)
        preview.write_bytes(b"png")
        seed_snapshot(workspace.root, NAME)
        seed_proposal(workspace.root, NAME)
        store = batch_naming(workspace, "b1", NAME, "someone-else")

        _rename(workspace, "hike-away")

        assert not workspace.listing_dir(NAME).exists()
        assert workspace.lock_file("hike-away").is_file()
        assert (workspace.renders_dir("hike-away") / "flat-lay-01" / "black.png").is_file()
        assert workspace.preview_file("hike-away", "flat-lay-01", "black", "deadbeef").is_file()
        assert not workspace.preview_dir(NAME).exists()
        assert workspace.market_snapshot_file("hike-away").is_file()
        assert not workspace.market_snapshot_file(NAME).exists()
        assert has_proposal(workspace.root, "hike-away")
        assert not has_proposal(workspace.root, NAME)
        assert [row.name for row in batch_rows(store, "b1")] == ["hike-away", "someone-else"]

    def test_forgets_the_old_names_ai_run(self, workspace: Workspace) -> None:
        """A new listing given the old name must not reattach to it."""
        runs, run = ai_run(NAME, finished=True)

        _rename(workspace, "hike-away", ai_runs=runs)

        assert runs.latest(NAME) is None
        assert run.stop_reason is None

    def test_the_same_name_changes_nothing(self, workspace: Workspace) -> None:
        """Blur commits an unchanged name constantly."""
        runs, run = ai_run(NAME, finished=True)

        _rename(workspace, NAME, ai_runs=runs)

        assert workspace.listing_file(NAME).is_file()
        assert runs.latest(NAME) is run

    def test_refuses_a_name_already_in_use(self, workspace: Workspace) -> None:
        workspace.listing_dir("taken").mkdir(parents=True)
        seed_proposal(workspace.root, NAME)

        with pytest.raises(ListingNameTaken):
            _rename(workspace, "taken")

        assert workspace.listing_file(NAME).is_file()
        assert has_proposal(workspace.root, NAME)

    def test_refuses_a_missing_listing(self, workspace: Workspace) -> None:
        with pytest.raises(ListingMissing):
            _rename(workspace, "whatever", old="no-such")

    def test_refuses_a_name_that_is_not_a_path_segment(self, workspace: Workspace) -> None:
        with pytest.raises(InvalidNameError):
            _rename(workspace, "../elsewhere")

        assert workspace.listing_file(NAME).is_file()


# ---------------------------------------------------------------- delete


class TestDeleteListing:
    def test_a_listing_with_no_remotes_is_wiped(self, workspace: Workspace) -> None:
        seed_snapshot(workspace.root, NAME)
        seed_proposal(workspace.root, NAME)

        deletion = _delete(workspace)

        assert deletion.wiped
        assert not workspace.listing_dir(NAME).exists()
        assert not workspace.market_snapshot_file(NAME).exists()
        assert not has_proposal(workspace.root, NAME)

    def test_a_listing_with_remotes_is_marked_pending_delete(self, workspace: Workspace) -> None:
        """The files stay for apply to retract the remotes; the market snapshot
        and the proposal go now -- the seller is done researching it."""
        applied(workspace, product_id="abc123")
        seed_snapshot(workspace.root, NAME)
        seed_proposal(workspace.root, NAME)

        deletion = _delete(workspace)

        assert not deletion.wiped
        assert _document(workspace)["lifecycle"] == "deleted"
        assert not workspace.market_snapshot_file(NAME).exists()
        assert not has_proposal(workspace.root, NAME)

    def test_a_published_listing_is_refused_and_nothing_changes(self, workspace: Workspace) -> None:
        """ADR-0035: retire it instead."""
        applied(workspace, etsy_listing_id=555)
        seed_proposal(workspace.root, NAME)
        store = batch_naming(workspace, "b1", NAME)
        runs, run = ai_run(NAME)
        before = workspace.listing_file(NAME).read_bytes()

        with pytest.raises(PublishedListingDeletion) as refused:
            _delete(workspace, ai_runs=runs, etsy_states=etsy_reports({555: "active"}))

        assert "published" in str(refused.value)
        assert workspace.listing_file(NAME).read_bytes() == before
        assert has_proposal(workspace.root, NAME)
        assert not batch_rows(store, "b1")[0].deleted
        assert (run.stop_reason, runs.latest(NAME)) == (None, run)

    def test_a_draft_etsy_listing_may_be_deleted(self, workspace: Workspace) -> None:
        applied(workspace, etsy_listing_id=555)

        deletion = _delete(workspace, etsy_states=etsy_reports({555: "draft"}))

        assert (deletion.wiped, deletion.etsy_state) == (False, "draft")

    def test_stops_and_forgets_the_listings_ai_run_and_marks_its_batch_rows(
        self, workspace: Workspace
    ) -> None:
        store = batch_naming(workspace, "b1", NAME, "someone-else")
        runs, run = ai_run(NAME)

        _delete(workspace, ai_runs=runs)

        assert run.stop_reason == "cancelled" and run.cancel_event.is_set()
        assert [(row.name, row.deleted) for row in batch_rows(store, "b1")] == [
            (NAME, True),
            ("someone-else", False),
        ]

    def test_forgets_the_listings_finished_ai_run(self, workspace: Workspace) -> None:
        """A new listing given the name must not reattach to it."""
        runs, _run = ai_run(NAME, finished=True)

        _delete(workspace, ai_runs=runs)

        assert runs.latest(NAME) is None

    def test_a_missing_listing_is_refused_and_touches_no_batch_row(
        self, workspace: Workspace
    ) -> None:
        store = batch_naming(workspace, "b1", "gone")
        runs, run = ai_run("gone", finished=True)

        with pytest.raises(ListingMissing):
            _delete(workspace, name="gone", ai_runs=runs)

        assert not batch_rows(store, "b1")[0].deleted
        assert runs.latest("gone") is run


# ------------------------------------------------------- competing writes


@pytest.fixture
def slow_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    real = yaml.safe_dump

    def slow(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        time.sleep(0.3)
        return real(*args, **kwargs)

    monkeypatch.setattr(yaml, "safe_dump", slow)


@pytest.fixture
def slow_renames(monkeypatch: pytest.MonkeyPatch) -> threading.Event:
    """Slows a rename's move. The event is set once a move has begun, which
    is to say once the rename holds the listing's lock."""
    real = Path.replace
    moving = threading.Event()

    def slow(self: Path, target: Any) -> Path:  # noqa: ANN401
        moving.set()
        time.sleep(0.3)
        return real(self, target)

    monkeypatch.setattr(Path, "replace", slow)
    return moving


def _together(*calls: Callable[[], object]) -> list[object]:
    """Start each call a moment after the one before, so they overlap in a
    known order; a raised refusal is returned in its place."""

    def outcome(call: Callable[[], object]) -> object:
        try:
            return call()
        except (ListingMissing, ListingNameTaken) as exc:
            return exc

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = []
        for call in calls:
            futures.append(pool.submit(outcome, call))
            time.sleep(0.1)
        return [future.result() for future in futures]


@pytest.mark.usefixtures("slow_writes")
class TestCompetingWrites:
    def test_two_concurrent_edits_both_land(self, workspace: Workspace) -> None:
        _together(
            lambda: _edit(workspace, {"brief": "A sunset hike."}),
            lambda: _edit(workspace, {"etsy": {"title": "Take A Hike Tee"}}),
        )

        written = _document(workspace)
        assert written["brief"] == "A sunset hike."
        assert written["etsy"]["title"] == "Take A Hike Tee"

    def test_an_edit_queued_behind_a_rename_finds_the_listing_gone(
        self, workspace: Workspace, slow_renames: threading.Event
    ) -> None:
        """It must not write a fresh ``listing.yaml`` under the old name. The
        edit starts only once the rename holds the lock, so the order is the
        one under test rather than whichever thread a busy runner ran first."""
        with ThreadPoolExecutor(max_workers=1) as pool:
            renaming = pool.submit(_rename, workspace, "hike-away")
            assert slow_renames.wait(timeout=10), "the rename never began its move"
            with pytest.raises(ListingMissing):
                _edit(workspace, {"brief": "Too late."})
            renaming.result()

        assert not workspace.listing_dir(NAME).exists()
        assert not workspace.listing_dir(NAME).exists()
        assert _document(workspace, "hike-away").get("brief") != "Too late."

    def test_a_create_and_a_rename_to_the_same_name_do_not_both_win(
        self, workspace: Workspace, slow_renames: threading.Event
    ) -> None:
        document = _document(workspace)

        outcomes = _together(
            lambda: _rename(workspace, "fresh"),
            lambda: create_listing(workspace, "fresh", document),
        )

        assert sorted(type(o).__name__ for o in outcomes) == ["ListingNameTaken", "NoneType"]
        assert workspace.listing_file("fresh").is_file()
