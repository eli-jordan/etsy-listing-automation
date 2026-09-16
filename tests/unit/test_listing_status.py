"""The four-state lifecycle rule, on its own (`engine/status.py`).

Pure, so the whole transition table fits here without a workspace, a lockfile
or a network. The end-to-end version -- where the three facts actually come
from -- is `tests/behaviour/test_listings_api.py`'s `TestListingStatus`.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from etsy_listings.engine.status import (
    edited_since_apply,
    is_live_etsy_state,
    listing_status,
)


class TestTheTransitionTable:
    def test_never_applied_is_a_draft(self) -> None:
        assert listing_status(applied=False, edited=False, live=False) == "draft"

    def test_applied_and_untouched_is_deployed(self) -> None:
        assert listing_status(applied=True, edited=False, live=False) == "deployed"

    def test_published_on_etsy_is_live(self) -> None:
        assert listing_status(applied=True, edited=False, live=True) == "live"

    def test_editing_something_never_published_goes_back_to_draft(self) -> None:
        """Nobody is looking at the stale copy, so there is nothing to
        distinguish it from work that has never been applied at all."""
        assert listing_status(applied=True, edited=True, live=False) == "draft"

    def test_editing_something_published_is_dirty(self) -> None:
        """The asymmetry with the case above: a buyer *is* looking at the
        stale copy, which is the gap `dirty` exists to name."""
        assert listing_status(applied=True, edited=True, live=True) == "dirty"

    def test_live_wins_over_never_applied(self) -> None:
        """Contradictory facts -- Etsy has it, the lockfile does not -- resolve
        towards what a shop visitor can see, which is the half a user cannot
        fix by re-running anything."""
        assert listing_status(applied=False, edited=False, live=True) == "live"


class TestWhatCountsAsLive:
    @pytest.mark.parametrize("state", ["active", "inactive", "sold_out", "expired", "removed"])
    def test_every_non_draft_state_counts(self, state: str) -> None:
        assert is_live_etsy_state(state)

    def test_a_draft_does_not(self) -> None:
        assert not is_live_etsy_state("draft")

    def test_an_unknown_answer_is_not_live(self) -> None:
        """A state we could not read is reported as not-live: that is the
        reading that never overstates what has happened to a shop."""
        assert not is_live_etsy_state(None)
        assert not is_live_etsy_state("something-etsy-added-later")


class TestEditedSinceApply:
    def _pair(self, tmp_path: Path, *, listing_offset: float) -> tuple[Path, Path]:
        listing = tmp_path / "listing.yaml"
        lock = tmp_path / "state.lock.json"
        listing.write_text("garment_profile: tee\n", encoding="utf-8")
        lock.write_text("{}", encoding="utf-8")
        stamp = time.time() + listing_offset
        os.utime(listing, (stamp, stamp))
        return listing, lock

    def test_a_listing_written_after_the_lockfile_counts_as_edited(self, tmp_path: Path) -> None:
        listing, lock = self._pair(tmp_path, listing_offset=10)
        assert edited_since_apply(listing, lock)

    def test_a_listing_older_than_the_lockfile_does_not(self, tmp_path: Path) -> None:
        listing, lock = self._pair(tmp_path, listing_offset=-10)
        assert not edited_since_apply(listing, lock)

    def test_no_lockfile_is_not_an_edit(self, tmp_path: Path) -> None:
        """ "Never applied" is a fact `listing_status` reads on its own; saying
        it twice would make a never-applied listing look edited."""
        listing = tmp_path / "listing.yaml"
        listing.write_text("garment_profile: tee\n", encoding="utf-8")
        assert not edited_since_apply(listing, tmp_path / "state.lock.json")

    def test_a_missing_listing_is_not_an_edit(self, tmp_path: Path) -> None:
        lock = tmp_path / "state.lock.json"
        lock.write_text("{}", encoding="utf-8")
        assert not edited_since_apply(tmp_path / "listing.yaml", lock)
