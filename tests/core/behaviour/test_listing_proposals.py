"""``core/application/ai/listing_proposals.py``: a listing's cached proposal
read and resolved directly -- no request, no server (ADR-0049; spec,
*Durable AI proposals*; module-structure plan, PR 9).

Staleness is judged against the saved listing on every read; accepting,
dismissing or reopening a section is recorded on the proposal it names and
nothing else; a regenerated proposal refuses a resolution meant for the old
one. Resolving never clears a proposal: only replacement, deletion, a fully
successful apply or clearing the cache does, which the runner's, the listing
operations' and the engine's tests pin. The HTTP mapping is
``tests/server/contract/test_proposals_api.py``'s.
"""

from __future__ import annotations

import threading
from datetime import timedelta
from pathlib import Path

import pytest

from etsy_listings.core.ai.listing_inputs import ListingAiInputs
from etsy_listings.core.ai.proposals import ProposalChoices, ProposalRecord, ProposalStore
from etsy_listings.core.application.ai.listing_proposals import read_proposal, resolve_proposal
from etsy_listings.core.application.refusals import (
    ListingMissing,
    ProposalMissing,
    ProposalReplaced,
)
from etsy_listings.core.listing_artifacts import remove_listing
from etsy_listings.core.workspace.listing_documents import ListingDocuments
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.ai_runs import TODAY, proposal_payload
from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import edit_listing


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


@pytest.fixture
def proposals(workspace: Workspace) -> ProposalStore:
    return ProposalStore(workspace)


def _generated(workspace: Workspace, proposals: ProposalStore) -> ProposalRecord:
    """A proposal as a run caches it: generated from the listing as saved."""
    return proposals.put(
        LISTING,
        ProposalChoices.model_validate_json(proposal_payload()),
        ListingAiInputs.read(workspace, LISTING).prepare().snapshot,
        generated_at=TODAY,
        origin="manual",
    )


def _resolve(workspace: Workspace, proposals: ProposalStore, **sections: object):  # noqa: ANN202
    return resolve_proposal(
        workspace,
        proposals,
        LISTING,
        generated_at=sections.pop("generated_at", TODAY),
        **sections,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------- reading


def test_a_fresh_proposal_reads_current_with_every_section_open(
    workspace: Workspace, proposals: ProposalStore
) -> None:
    record = _generated(workspace, proposals)

    proposal = read_proposal(workspace, proposals, LISTING)

    assert (proposal.proposal, proposal.generated_at) == (record.proposal, TODAY)
    assert (proposal.stale.is_stale, proposal.stale.reasons) == (False, [])
    assert proposal.resolution.model_dump() == {
        "title": "pending",
        "tags": "pending",
        "lead": "pending",
    }


def test_an_edit_since_generation_reads_stale_and_still_usable(
    workspace: Workspace, workspace_root: Path, proposals: ProposalStore
) -> None:
    _generated(workspace, proposals)
    edit_listing(workspace_root, brief="A different brief altogether.")

    proposal = read_proposal(workspace, proposals, LISTING)

    assert proposal.stale.is_stale
    assert proposal.stale.reasons == ["brief edited since"]
    assert proposals.load(LISTING) is not None, "a stale proposal is kept"


def test_reading_refuses_a_missing_listing_or_proposal(
    workspace: Workspace, proposals: ProposalStore
) -> None:
    with pytest.raises(ProposalMissing, match="no proposal for 'take-a-hike'"):
        read_proposal(workspace, proposals, LISTING)
    with pytest.raises(ListingMissing):
        read_proposal(workspace, proposals, "never-saved")


# -------------------------------------------------------------- resolving


def test_accepting_and_dismissing_are_recorded_and_survive_a_reread(
    workspace: Workspace, proposals: ProposalStore
) -> None:
    _generated(workspace, proposals)

    resolved = _resolve(workspace, proposals, title="accepted", lead="dismissed")

    expected = {"title": "accepted", "tags": "pending", "lead": "dismissed"}
    assert resolved.resolution.model_dump() == expected
    assert read_proposal(workspace, proposals, LISTING).resolution.model_dump() == expected


def test_a_section_can_be_reopened(workspace: Workspace, proposals: ProposalStore) -> None:
    _generated(workspace, proposals)
    _resolve(workspace, proposals, tags="accepted")

    reopened = _resolve(workspace, proposals, tags="pending")

    assert reopened.resolution.tags == "pending"


def test_resolving_every_section_keeps_the_proposal(
    workspace: Workspace, proposals: ProposalStore
) -> None:
    """ADR-0049: resolution is not one of the rules that clear a proposal."""
    _generated(workspace, proposals)

    _resolve(workspace, proposals, title="accepted", tags="accepted", lead="dismissed")

    assert proposals.load(LISTING) is not None


def test_a_resolution_for_a_replaced_proposal_is_refused_and_changes_nothing(
    workspace: Workspace, proposals: ProposalStore
) -> None:
    _generated(workspace, proposals)

    with pytest.raises(ProposalReplaced):
        _resolve(workspace, proposals, generated_at=TODAY - timedelta(minutes=5), title="accepted")

    assert read_proposal(workspace, proposals, LISTING).resolution.title == "pending"


def test_resolving_refuses_a_missing_listing_or_proposal(
    workspace: Workspace, proposals: ProposalStore
) -> None:
    with pytest.raises(ProposalMissing):
        _resolve(workspace, proposals, title="accepted")
    with pytest.raises(ListingMissing):
        resolve_proposal(
            workspace,
            proposals,
            "never-saved",
            generated_at=TODAY,
            title="accepted",
        )


def test_a_listing_deleted_while_resolving_waits_is_refused_and_leaves_no_record(
    workspace: Workspace, proposals: ProposalStore
) -> None:
    """Under the listing's write lock: a delete holding it lands first, and
    the resolution re-checks the listing rather than writing a record back
    for a listing that is gone."""
    _generated(workspace, proposals)
    documents = ListingDocuments(workspace)
    refused: list[BaseException] = []

    def resolve() -> None:
        try:
            resolve_proposal(workspace, proposals, LISTING, generated_at=TODAY, title="accepted")
        except ListingMissing as exc:
            refused.append(exc)

    with documents.lock(LISTING):
        waiting = threading.Thread(target=resolve)
        waiting.start()
        waiting.join(timeout=0.2)
        assert waiting.is_alive(), "the resolution did not wait for the lock"
        proposals.remove(LISTING)
        remove_listing(workspace, LISTING)
    waiting.join(timeout=5)

    assert len(refused) == 1
    assert proposals.load(LISTING) is None
