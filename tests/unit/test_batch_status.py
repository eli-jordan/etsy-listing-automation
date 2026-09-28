"""A batch's derived status (UI doc §2, *Recent batches*; spec *Review
workflow*; batch plan PR 5): worked out from its rows on every read, never
set by hand. Each test is a row of the UI doc's table, or one of the notes
under it.

*Staging* is not here: it is a staging session, which has no rows of this
kind yet, and the index says so without asking.
"""

from __future__ import annotations

from typing import Any

from etsy_listings.batches import BatchRow, reviewable, standing


def _row(n: int, **fields: Any) -> BatchRow:  # noqa: ANN401
    values: dict[str, Any] = {"creation": "created", "ai": "done"} | fields
    return BatchRow(
        id=f"r{n}",
        sha256=f"{n:064x}",
        sources=[f"d{n}.png"],
        base=f"d{n}",
        name=f"d{n}",
        design=f"d{n}",
        **values,
    )


def _status(*rows: BatchRow) -> str:
    return standing(list(rows)).status


# ------------------------------------------------------------ the table


def test_drafting_while_the_queue_still_has_work_for_a_listing() -> None:
    assert _status(_row(1), _row(2, ai="running"), _row(3, ai="queued")) == "drafting"
    assert _status(_row(1, reviewed=True), _row(2, ai="queued")) == "drafting"


def test_in_review_once_drafting_is_done_and_a_listing_is_not_reviewed() -> None:
    assert _status(_row(1, reviewed=True), _row(2)) == "in_review"


def test_complete_when_every_created_listing_is_reviewed() -> None:
    assert _status(_row(1, reviewed=True), _row(2, reviewed=True)) == "complete"


def test_stopped_when_cancel_batch_left_work_undrafted() -> None:
    assert _status(_row(1, reviewed=True), _row(2, ai="stopped")) == "stopped"
    assert _status(_row(1), _row(2, ai="cancelled")) == "stopped"


# ------------------------------------------------------ the notes under it


def test_marking_the_last_listing_reviewed_completes_it_and_one_back_reopens_it() -> None:
    rows = [_row(1, reviewed=True), _row(2)]
    assert _status(*rows) == "in_review"

    rows[1] = rows[1].model_copy(update={"reviewed": True})
    assert _status(*rows) == "complete"

    rows[0] = rows[0].model_copy(update={"reviewed": False})
    assert _status(*rows) == "in_review"


def test_a_failed_row_never_changes_the_status() -> None:
    """Failures are a count beside the progress, not a status: the same
    batch with and without the failure reads the same."""
    ai_failed = _row(9, ai="failed", ai_error="Market research timed out")
    not_created = _row(8, creation="failed", ai=None, error="Couldn't write designs/")
    for rows, status in [
        ([_row(1, ai="running")], "drafting"),
        ([_row(1, reviewed=True), _row(2)], "in_review"),
        ([_row(1, reviewed=True)], "complete"),
        ([_row(1), _row(2, ai="stopped")], "stopped"),
    ]:
        assert _status(*rows) == status
        assert _status(*rows, not_created) == status
        if status != "complete":  # a failed listing still has to be reviewed
            assert _status(*rows, ai_failed) == status


def test_a_failed_row_the_seller_reviewed_by_hand_counts_as_reviewed() -> None:
    finished_by_hand = _row(2, ai="failed", reviewed=True)

    assert _status(_row(1, reviewed=True), finished_by_hand) == "complete"


def test_failures_are_counted_whether_creation_or_ai_failed() -> None:
    rows = [
        _row(1),
        _row(2, ai="failed"),
        _row(3, creation="failed", ai=None),
        _row(4, ai="failed", deleted=True),
    ]

    assert standing(rows).failures == 2


def test_a_deleted_listing_is_not_waited_for() -> None:
    """UI doc §7: a deleted listing leaves a struck-through row, and there
    is nothing left of it to review."""
    assert _status(_row(1, reviewed=True), _row(2, deleted=True)) == "complete"
    assert _status(_row(1, reviewed=True), _row(2, ai="cancelled", deleted=True)) == "complete"


def test_complete_does_not_need_deploying() -> None:
    """Nothing about deploying is a row's: reviewing every listing is all
    Complete asks (UI doc §2)."""
    assert _status(_row(1, reviewed=True)) == "complete"


def test_a_batch_with_no_listing_left_to_review_is_in_review_not_complete() -> None:
    """Nothing created, or everything deleted: *Complete* would claim a
    review that never happened."""
    assert _status(_row(1, creation="failed", ai=None)) == "in_review"
    assert _status(_row(1, deleted=True)) == "in_review"


def test_the_progress_counts() -> None:
    rows = [
        _row(1, reviewed=True),
        _row(2),
        _row(3, ai="running"),
        _row(4, ai="stopped"),
        _row(5, ai="failed"),
        _row(6, creation="failed", ai=None),
        _row(7, deleted=True, reviewed=True),
    ]

    counts = standing(rows)

    assert (counts.listings, counts.drafted, counts.reviewed, counts.undrafted) == (5, 2, 1, 1)


# ------------------------------------------------------------ reviewable


def test_only_a_listing_the_seller_can_look_at_is_reviewable() -> None:
    """UI doc §7: not on queued, drafting, deleted or never-created rows."""
    for row in [_row(1), _row(2, ai="failed"), _row(3, ai="stopped"), _row(4, ai="cancelled")]:
        assert reviewable(row), row.ai
    for row in [
        _row(5, ai="queued"),
        _row(6, ai="running"),
        _row(7, deleted=True),
        _row(8, creation="failed", ai=None),
        _row(9, creation="pending", ai=None),
    ]:
        assert not reviewable(row), row
