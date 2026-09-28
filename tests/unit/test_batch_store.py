"""`BatchStore`'s listing hooks and review flag (A42; spec *Review
workflow*; batch plan PR 5): a row follows its listing's current name, is
marked deleted with it, and is marked reviewed only while there is a
listing to review.

A row names its listing exactly, as a proposal record does: two listings
differing only in case can coexist on a case-sensitive filesystem, and
renaming or deleting one must not reach the other's row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from etsy_listings.batches import Batch, BatchRow, BatchStore, NotReviewable
from etsy_listings.workspace.workspace import Workspace

CREATED = datetime(2026, 9, 27, 11, 42, tzinfo=UTC)


def _row(name: str, **fields: Any) -> BatchRow:  # noqa: ANN401
    values: dict[str, Any] = {"creation": "created", "ai": "done", "design": name} | fields
    return BatchRow(
        id=f"row-{name}",
        sha256="0" * 64,
        sources=[f"{name}.png"],
        base=name,
        name=name,
        **values,
    )


@pytest.fixture
def store(workspace_root: Path) -> BatchStore:
    return BatchStore(Workspace.discover(root_override=workspace_root))


def _save(store: BatchStore, batch_id: str, *rows: BatchRow) -> None:
    store.save(
        Batch(
            id=batch_id,
            listing_template="heavyweight-tee",
            template={},
            template_saved_at=CREATED,
            label=batch_id,
            created_at=CREATED,
            rows=list(rows),
        )
    )


def _rows(store: BatchStore, batch_id: str) -> list[BatchRow]:
    batch = store.load(batch_id)
    assert batch is not None
    return batch.rows


# ---------------------------------------------------------------- rename


def test_renaming_a_listing_renames_its_row_in_every_batch(store: BatchStore) -> None:
    _save(store, "b1", _row("cedar-trail"), _row("lake-loop"))
    _save(store, "b2", _row("cedar-trail", deleted=True))

    store.rename_listing("cedar-trail", "cedar-ridge")

    assert [(r.name, r.design) for r in _rows(store, "b1")] == [
        ("cedar-ridge", "cedar-trail"),
        ("lake-loop", "lake-loop"),
    ]
    # A deleted row names a listing that is gone; a new one given the name
    # is not its listing.
    assert [r.name for r in _rows(store, "b2")] == ["cedar-trail"]


def test_a_rename_matches_the_exact_name_not_its_casefold(store: BatchStore) -> None:
    _save(store, "b1", _row("cedar"), _row("Cedar"))

    store.rename_listing("Cedar", "ridge")

    assert [r.name for r in _rows(store, "b1")] == ["cedar", "ridge"]


def test_a_rename_that_fails_leaves_the_rows_alone(store: BatchStore) -> None:
    """The listings API moves the directory inside `following_rename`; a
    move refused there -- the new name taken -- must not rename the rows."""
    _save(store, "b1", _row("cedar"))

    with pytest.raises(FileExistsError), store.following_rename("cedar", "ridge"):
        raise FileExistsError("ridge")

    assert [r.name for r in _rows(store, "b1")] == ["cedar"]


def test_a_case_only_rename_follows_the_listing(store: BatchStore) -> None:
    _save(store, "b1", _row("cedar"))

    store.rename_listing("cedar", "Cedar")

    assert [r.name for r in _rows(store, "b1")] == ["Cedar"]


# ---------------------------------------------------------------- delete


def test_deleting_a_listing_marks_its_row_and_takes_it_out_of_the_queue(
    store: BatchStore,
) -> None:
    _save(store, "b1", _row("cedar", ai="queued"), _row("lake", ai="queued"))

    store.mark_deleted("cedar")

    assert [(r.name, r.deleted, r.ai) for r in _rows(store, "b1")] == [
        ("cedar", True, "cancelled"),
        ("lake", False, "queued"),
    ]


def test_deleting_a_listing_leaves_a_running_row_to_its_run(store: BatchStore) -> None:
    """The run is asked to stop by the delete, and its end records
    ``cancelled`` on the row as any stopped run's does."""
    _save(store, "b1", _row("cedar", ai="running"))

    store.mark_deleted("cedar")

    assert [(r.deleted, r.ai) for r in _rows(store, "b1")] == [(True, "running")]


def test_a_delete_matches_the_exact_name_not_its_casefold(store: BatchStore) -> None:
    _save(store, "b1", _row("cedar"), _row("Cedar"))

    store.mark_deleted("Cedar")

    assert [r.deleted for r in _rows(store, "b1")] == [False, True]


def test_a_row_that_was_never_created_has_no_listing_to_delete(store: BatchStore) -> None:
    _save(store, "b1", _row("cedar", creation="failed", ai=None))

    store.mark_deleted("cedar")

    assert [r.deleted for r in _rows(store, "b1")] == [False]


# ---------------------------------------------------------------- review


def test_review_sets_and_clears_the_flag(store: BatchStore) -> None:
    _save(store, "b1", _row("cedar"))

    store.review("b1", "row-cedar", reviewed=True)
    assert [r.reviewed for r in _rows(store, "b1")] == [True]

    store.review("b1", "row-cedar", reviewed=False)
    assert [r.reviewed for r in _rows(store, "b1")] == [False]


def test_review_refuses_a_row_with_no_listing_to_look_at(store: BatchStore) -> None:
    _save(store, "b1", _row("queued", ai="queued"), _row("gone", deleted=True))

    for row in ("row-queued", "row-gone"):
        with pytest.raises(NotReviewable):
            store.review("b1", row, reviewed=True)
    assert [r.reviewed for r in _rows(store, "b1")] == [False, False]


def test_review_of_an_unknown_batch_or_row_is_a_key_error(store: BatchStore) -> None:
    _save(store, "b1", _row("cedar"))

    with pytest.raises(KeyError):
        store.review("b1", "row-nope", reviewed=True)
    with pytest.raises(KeyError):
        store.review("nope", "row-cedar", reviewed=True)


# ---------------------------------------------------------------- remove


def test_remove_forgets_the_record_and_its_directory(
    store: BatchStore, workspace_root: Path
) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    _save(store, "b1", _row("cedar"))
    workspace.batch_upload_file("b1", "0" * 64).parent.mkdir(parents=True)

    store.remove("b1")

    assert store.load("b1") is None
    assert workspace.batch_ids() == []
    assert not workspace.batch_dir("b1").exists()


def test_a_restore_brings_back_only_the_rows_for_that_listing_s_design(
    store: BatchStore,
) -> None:
    """A row for an earlier listing wiped under the same name names another
    design, and stays deleted."""
    _save(store, "b1", _row("cedar", deleted=True))
    _save(store, "b2", _row("cedar", deleted=True, design="cedar-old"))

    store.restore_listing("cedar", "designs/cedar.png")

    assert [r.deleted for r in _rows(store, "b1")] == [False]
    assert [r.deleted for r in _rows(store, "b2")] == [True]
