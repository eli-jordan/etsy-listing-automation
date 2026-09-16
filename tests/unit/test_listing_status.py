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
    listing_gestures,
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


class TestTheIncompleteMarker:
    """A29. A per-stage lockfile write makes `state.lock.json` newer than
    `listing.yaml` partway through a deploy that then fails, so
    `edited_since_apply` alone would read a partially-applied live listing as
    clean. A set marker must read exactly like an edit would."""

    def test_a_marked_live_listing_reads_dirty_even_though_nothing_looks_edited(self) -> None:
        assert listing_status(applied=True, edited=False, live=True, incomplete=True) == "dirty"

    def test_an_unmarked_live_listing_still_reads_live(self) -> None:
        assert listing_status(applied=True, edited=False, live=True, incomplete=False) == "live"

    def test_the_marker_does_not_invent_a_new_status_for_a_never_applied_listing(self) -> None:
        """Never live and never fully applied is `draft` regardless -- the
        marker piggybacks on the existing `edited` branch rather than adding
        a state of its own."""
        assert listing_status(applied=False, edited=False, live=False, incomplete=True) == "draft"

    def test_delete_retire_still_win_over_a_marked_listing(self) -> None:
        """PRD 61-67's lifecycle badges take precedence over live/dirty
        already; the marker must not change that ordering."""
        assert (
            listing_status(
                applied=True,
                edited=False,
                live=True,
                lifecycle="retired",
                etsy_state="active",
                incomplete=True,
            )
            == "pending-retire"
        )


class TestDeleteAndRetireBadges:
    """PRD 61–67: the original four remain; these add, and win when both
    could apply. `live` still means "has left draft"; `etsy_state` names
    which published condition, so inactive/expired are not painted live."""

    def test_lifecycle_deleted_is_pending_delete(self) -> None:
        assert (
            listing_status(applied=True, edited=False, live=False, lifecycle="deleted")
            == "pending-delete"
        )

    def test_retired_while_etsy_is_still_active_is_pending_retire(self) -> None:
        assert (
            listing_status(
                applied=True,
                edited=False,
                live=True,
                lifecycle="retired",
                etsy_state="active",
            )
            == "pending-retire"
        )

    def test_retired_applied_and_etsy_inactive_is_inactive(self) -> None:
        assert (
            listing_status(
                applied=True,
                edited=False,
                live=True,
                lifecycle="retired",
                etsy_state="inactive",
                last_applied_lifecycle="retired",
            )
            == "inactive"
        )

    def test_edits_while_retired_stay_retired(self) -> None:
        """A typo fix must not paint the row dirty — Un-retire is its own
        gesture, not a side-effect of saving the yaml."""
        assert (
            listing_status(
                applied=True,
                edited=True,
                live=True,
                lifecycle="retired",
                etsy_state="inactive",
                last_applied_lifecycle="retired",
            )
            == "inactive"
        )

    def test_etsy_paused_us_is_inactive_until_we_renew(self) -> None:
        assert (
            listing_status(applied=True, edited=False, live=True, etsy_state="inactive")
            == "inactive"
        )

    def test_etsy_removed_us_is_inactive_until_we_renew(self) -> None:
        assert (
            listing_status(applied=True, edited=False, live=True, etsy_state="removed")
            == "inactive"
        )

    def test_etsy_expired_is_named_because_money(self) -> None:
        assert (
            listing_status(applied=True, edited=False, live=True, etsy_state="expired") == "expired"
        )

    def test_sold_out_stays_live(self) -> None:
        """Inventory, not a pause — apply does not treat it as retirement."""
        assert (
            listing_status(applied=True, edited=False, live=True, etsy_state="sold_out") == "live"
        )

    def test_un_retire_is_draft_because_we_want_it_on_sale(self) -> None:
        assert (
            listing_status(
                applied=True,
                edited=False,
                live=True,
                etsy_state="inactive",
                last_applied_lifecycle="retired",
            )
            == "draft"
        )

    def test_pending_renew_is_draft(self) -> None:
        assert (
            listing_status(
                applied=True,
                edited=False,
                live=True,
                lifecycle="renew",
                etsy_state="expired",
            )
            == "draft"
        )

    def test_adopting_a_remote_pause_is_inactive_not_pending_retire(self) -> None:
        """Retire on an already-inactive listing writes `retired`; Etsy is
        not still active, so calling it pending-retire would lie."""
        assert (
            listing_status(
                applied=True,
                edited=False,
                live=True,
                lifecycle="retired",
                etsy_state="inactive",
            )
            == "inactive"
        )


class TestGestures:
    """PRD 66: which buttons the listings table offers. Derived from the
    same facts as the badge, so the two cannot disagree about the row."""

    def test_never_live_is_delete(self) -> None:
        assert listing_gestures(published=False) == ("delete",)

    def test_live_with_no_lifecycle_is_retire(self) -> None:
        assert listing_gestures(published=True, etsy_state="active") == ("retire",)

    def test_pending_retire_is_un_retire(self) -> None:
        assert listing_gestures(lifecycle="retired", etsy_state="active") == ("un-retire",)

    def test_retired_applied_is_un_retire(self) -> None:
        assert listing_gestures(lifecycle="retired", etsy_state="inactive") == ("un-retire",)

    def test_pending_delete_is_cancel(self) -> None:
        assert listing_gestures(lifecycle="deleted") == ("cancel",)

    def test_etsy_paused_us_is_retire_and_renew(self) -> None:
        assert listing_gestures(published=True, etsy_state="inactive") == (
            "retire",
            "renew",
        )

    def test_expired_is_retire_and_renew(self) -> None:
        assert listing_gestures(published=True, etsy_state="expired") == (
            "retire",
            "renew",
        )

    def test_sold_out_is_retire_only(self) -> None:
        assert listing_gestures(published=True, etsy_state="sold_out") == ("retire",)


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
