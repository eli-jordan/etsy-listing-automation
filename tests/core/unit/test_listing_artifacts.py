"""Everything keyed by a listing's name, moved and removed together.

Rename, wipe and a pending delete work from one list, so each test here
seeds every artifact and checks that all of them followed. A store missing
from the list fails here, not in a seller's workspace.
"""

from __future__ import annotations

import stat
import threading
from pathlib import Path

import pytest

from etsy_listings.core.listing_artifacts import discard_research, move_listing, remove_listing
from etsy_listings.core.workspace.listing_documents import (
    ListingDocuments,
    ListingMissing,
    ListingNameTaken,
)
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.ai_runs import has_proposal, seed_proposal, seed_snapshot
from tests.support.builders import FIXTURE_LISTING as NAME


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


def _seed_caches(workspace: Workspace, name: str = NAME) -> None:
    render = workspace.renders_dir(name) / "flat-lay-01" / "black.png"
    render.parent.mkdir(parents=True)
    render.write_bytes(b"render")
    preview = workspace.preview_file(name, "flat-lay-01", "black", "deadbeef")
    preview.parent.mkdir(parents=True)
    preview.write_bytes(b"preview")
    seed_snapshot(workspace.root, name)
    seed_proposal(workspace.root, name)


def _keyed_by(workspace: Workspace, name: str) -> dict[str, bool]:
    return {
        "listing": workspace.listing_file(name).is_file(),
        "renders": workspace.renders_dir(name).is_dir(),
        "previews": workspace.preview_dir(name).is_dir(),
        "snapshot": workspace.market_snapshot_file(name).is_file(),
        "proposal": has_proposal(workspace.root, name),
    }


class TestMove:
    def test_everything_keyed_by_the_name_follows(self, workspace: Workspace) -> None:
        _seed_caches(workspace)

        move_listing(workspace, NAME, "hike-away")

        assert set(_keyed_by(workspace, "hike-away").values()) == {True}
        assert set(_keyed_by(workspace, NAME).values()) == {False}

    def test_leftover_caches_at_the_new_name_are_replaced(self, workspace: Workspace) -> None:
        """A free name's caches belong to no listing. They must not block the
        move or survive it."""
        _seed_caches(workspace)
        stale = workspace.preview_file("hike-away", "flat-lay-01", "black", "stale")
        stale.parent.mkdir(parents=True)
        stale.write_bytes(b"stale")

        move_listing(workspace, NAME, "hike-away")

        assert not stale.exists()
        assert workspace.preview_file("hike-away", "flat-lay-01", "black", "deadbeef").is_file()

    def test_refuses_a_missing_listing(self, workspace: Workspace) -> None:
        with pytest.raises(ListingMissing):
            move_listing(workspace, "no-such", "whatever")

    def test_refuses_a_taken_name_and_moves_nothing(self, workspace: Workspace) -> None:
        _seed_caches(workspace)
        workspace.listing_dir("taken").mkdir(parents=True)

        with pytest.raises(ListingNameTaken):
            move_listing(workspace, NAME, "taken")

        assert set(_keyed_by(workspace, NAME).values()) == {True}

    def test_waits_for_a_writer_holding_the_listings_lock(self, workspace: Workspace) -> None:
        documents = ListingDocuments(workspace)
        moved = threading.Event()

        with documents.lock(NAME):
            mover = threading.Thread(
                target=lambda: (move_listing(workspace, NAME, "hike-away"), moved.set())
            )
            mover.start()
            assert not moved.wait(0.2)
            assert documents.exists(NAME)
        mover.join(timeout=5)

        assert moved.is_set()
        assert documents.exists("hike-away")


class TestRemove:
    def test_everything_keyed_by_the_name_goes(self, workspace: Workspace) -> None:
        _seed_caches(workspace)

        remove_listing(workspace, NAME)

        assert set(_keyed_by(workspace, NAME).values()) == {False}
        assert not workspace.listing_dir(NAME).exists()

    def test_another_listings_artifacts_stay(self, workspace: Workspace) -> None:
        _seed_caches(workspace, "another-listing")

        remove_listing(workspace, NAME)

        keyed = _keyed_by(workspace, "another-listing")
        assert {key: keyed[key] for key in ("renders", "previews", "snapshot", "proposal")} == {
            "renders": True,
            "previews": True,
            "snapshot": True,
            "proposal": True,
        }

    def test_survives_a_read_only_listing_directory(self, workspace: Workspace) -> None:
        """The bug as a seller met it: Delete wiped ``listing.yaml`` and then
        failed on the directory, leaving an empty husk the listings table
        still showed."""
        listing_dir = workspace.listing_dir(NAME)
        listing_dir.chmod(stat.S_IREAD | stat.S_IEXEC)

        remove_listing(workspace, NAME)

        assert not listing_dir.exists()


class TestDiscardResearch:
    def test_the_snapshot_and_proposal_go_and_the_listing_stays(self, workspace: Workspace) -> None:
        _seed_caches(workspace)

        discard_research(workspace, NAME)

        assert _keyed_by(workspace, NAME) == {
            "listing": True,
            "renders": True,
            "previews": True,
            "snapshot": False,
            "proposal": False,
        }
