"""One latest proposal per listing, in ``.cache/proposals/`` (A37, A41).

The store is the only reader and writer of those records: a proposal saved
is the proposal loaded, a newer one replaces it with every section open
again, a section's resolution sticks, and rename and delete carry the record
with the listing (A42). A record this code cannot read -- a schema it does
not know, a file that is not JSON -- is no record, because it is cache.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from etsy_listings.ai.proposals import (
    ProposalChoices,
    ProposalReplacedError,
    ProposalStore,
    SeoProposalSnapshot,
)
from etsy_listings.workspace.workspace import Workspace

from tests.support.refusals import refuse_reads

GENERATED = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 9, 25, 9, 30, tzinfo=UTC)


def _choices(title: str = "Retro Sunset Hike Tee") -> ProposalChoices:
    return ProposalChoices(
        titles=[title, "Take A Hike Graphic Shirt", "Mountain Trail Tee"],
        tags=[f"tag{i}" for i in range(20)],
        description_leads=["lead one", "lead two", "lead three"],
        rationale=[],
        warnings=[],
        observed_text="TAKE A HIKE",
    )


def _snapshot() -> SeoProposalSnapshot:
    return SeoProposalSnapshot(
        brief="Retro sunset.",
        product_type="Tee",
        etsy_category="",
        materials=["cotton"],
        colors=["black"],
        garment_brand="Comfort Colors",
        garment_model="1717",
        garment_profile="comfort-colors-1717",
        design={"default": "designs/take-a-hike.png"},
        design_content_hash="3f1c",
    )


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


@pytest.fixture
def store(workspace: Workspace) -> ProposalStore:
    return ProposalStore(workspace)


def _put(
    store: ProposalStore,
    listing: str = "take-a-hike",
    *,
    choices: ProposalChoices | None = None,
    generated_at: datetime = GENERATED,
) -> None:
    store.put(
        listing, choices or _choices(), _snapshot(), generated_at=generated_at, origin="manual"
    )


def test_a_saved_proposal_loads_back_with_every_section_pending(store: ProposalStore) -> None:
    _put(store)

    record = store.load("take-a-hike")

    assert record is not None
    assert record.proposal == _choices()
    assert record.snapshot == _snapshot()
    assert record.generated_at == GENERATED
    assert record.origin == "manual"
    assert record.resolution.model_dump() == {
        "title": "pending",
        "tags": "pending",
        "lead": "pending",
    }


def test_no_proposal_is_none(store: ProposalStore) -> None:
    assert store.load("take-a-hike") is None


def test_a_proposal_read_while_it_is_replaced_is_still_there(
    store: ProposalStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows refuses to open a record mid-replace; a read that lands there
    waits the save out rather than finding no proposal (A37)."""
    _put(store)
    refuse_reads(monkeypatch, 3)

    record = store.load("take-a-hike")

    assert record is not None
    assert record.proposal == _choices()


def test_a_proposal_that_stays_unreadable_is_no_proposal(
    store: ProposalStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _put(store)
    refuse_reads(monkeypatch, 1000)

    assert store.load("take-a-hike") is None


def test_a_proposal_survives_a_new_store(workspace: Workspace, store: ProposalStore) -> None:
    _put(store)

    assert ProposalStore(workspace).load("take-a-hike") is not None


def test_resolving_a_section_leaves_the_others_open(store: ProposalStore) -> None:
    _put(store)

    store.resolve("take-a-hike", generated_at=GENERATED, title="accepted", tags="dismissed")

    record = store.load("take-a-hike")
    assert record is not None
    assert record.resolution.model_dump() == {
        "title": "accepted",
        "tags": "dismissed",
        "lead": "pending",
    }


def test_resolving_a_replaced_proposal_is_refused(store: ProposalStore) -> None:
    """The seller clicked on the proposal the page showed; a regeneration
    that landed meanwhile is a different one, and stays open."""
    _put(store)
    _put(store, choices=_choices("Fresh Title"), generated_at=LATER)

    with pytest.raises(ProposalReplacedError):
        store.resolve("take-a-hike", generated_at=GENERATED, title="accepted")

    record = store.load("take-a-hike")
    assert record is not None
    assert record.resolution.title == "pending"


def test_resolving_nothing_stored_is_none(store: ProposalStore) -> None:
    assert store.resolve("take-a-hike", generated_at=GENERATED, lead="dismissed") is None


def test_a_regenerated_proposal_replaces_the_last_and_reopens_it(store: ProposalStore) -> None:
    _put(store)
    store.resolve("take-a-hike", generated_at=GENERATED, title="accepted")

    _put(store, choices=_choices("Fresh Title"), generated_at=LATER)

    record = store.load("take-a-hike")
    assert record is not None
    assert record.proposal.titles[0] == "Fresh Title"
    assert record.generated_at == LATER
    assert record.resolution.title == "pending"


def test_move_carries_the_record_to_the_new_name(store: ProposalStore) -> None:
    _put(store)
    store.resolve("take-a-hike", generated_at=GENERATED, lead="accepted")

    store.move("take-a-hike", "go-hiking")

    assert store.load("take-a-hike") is None
    moved = store.load("go-hiking")
    assert moved is not None
    assert moved.resolution.lead == "accepted"


def test_moving_a_listing_with_no_proposal_is_nothing(store: ProposalStore) -> None:
    store.move("take-a-hike", "go-hiking")

    assert store.load("go-hiking") is None


def test_a_case_only_rename_keeps_the_record(store: ProposalStore) -> None:
    """On a case-insensitive filesystem the two names are one file: the
    move must not delete what it has just written."""
    _put(store)

    store.move("take-a-hike", "Take-A-Hike")

    assert store.load("Take-A-Hike") is not None


def test_remove_forgets_it(store: ProposalStore) -> None:
    _put(store)

    store.remove("take-a-hike")
    store.remove("take-a-hike")

    assert store.load("take-a-hike") is None


def test_a_record_is_read_back_only_under_the_name_that_wrote_it(
    store: ProposalStore,
) -> None:
    """On a case-insensitive filesystem both spellings open one file; the
    record names its listing, so the other spelling still reads nothing."""
    _put(store, "Take-A-Hike")

    assert store.load("take-a-hike") is None


@pytest.mark.parametrize("content", ["not json", '{"schema": 99}', '["a list"]'])
def test_an_unreadable_record_is_no_record(
    workspace: Workspace, store: ProposalStore, content: str
) -> None:
    path = workspace.proposal_file("take-a-hike")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

    assert store.load("take-a-hike") is None


def test_the_record_is_schema_versioned_json_under_the_exact_name(
    workspace: Workspace, store: ProposalStore
) -> None:
    """A37 and PRD 4's layout: ``.cache/proposals/<listing>.json``. Not the
    casefold, which gave two listings differing only in case one file."""
    _put(store, "Take-A-Hike")

    raw = json.loads(workspace.proposal_file("Take-A-Hike").read_text(encoding="utf-8"))

    assert workspace.proposal_file("Take-A-Hike").name == "Take-A-Hike.json"
    # Names, not paths: a WindowsPath compares case-insensitively.
    assert workspace.proposal_file("take-a-hike").name == "take-a-hike.json"
    assert raw["schema"] == 1
    assert raw["listing"] == "Take-A-Hike"


def test_removing_a_listing_removes_its_proposal(
    workspace: Workspace, store: ProposalStore
) -> None:
    _put(store)

    workspace.remove_listing("take-a-hike")

    assert store.load("take-a-hike") is None


def _case_sensitive(directory: Path) -> bool:
    probe = directory / "Case-Probe"
    probe.write_text("", encoding="utf-8")
    try:
        return not (directory / "case-probe").exists()
    finally:
        probe.unlink()


def test_listings_differing_only_in_case_keep_their_own_proposals(
    workspace: Workspace, store: ProposalStore, tmp_path: Path
) -> None:
    """Only a case-sensitive filesystem (Linux) can hold both listings.
    Removing one, by either destructive path, leaves the other's record."""
    if not _case_sensitive(tmp_path):
        pytest.skip("this filesystem cannot hold two names differing only in case")
    _put(store, "take-a-hike")
    _put(store, "Take-A-Hike", choices=_choices("The Other Listing"))

    workspace.remove_listing("take-a-hike")
    store.move("Take-A-Hike", "Take-A-Hike-2")

    assert store.load("take-a-hike") is None
    other = store.load("Take-A-Hike-2")
    assert other is not None
    assert other.proposal.titles[0] == "The Other Listing"
