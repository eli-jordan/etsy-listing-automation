from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from etsy_listings.core.ai.listing_inputs import ListingAiInputs
from etsy_listings.core.ai.proposals import (
    ListingProposal,
    ProposalStore,
    Resolution,
)
from etsy_listings.core.ai.proposals import (
    ProposalReplacedError as CachedProposalReplacedError,
)
from etsy_listings.core.application.refusals import (
    ListingMissingError,
    ProposalMissingError,
    ProposalReplacedError,
)
from etsy_listings.core.workspace.listing_documents import ListingDocuments
from etsy_listings.core.workspace.workspace import Workspace


def read_proposal(workspace: Workspace, proposals: ProposalStore, name: str) -> ListingProposal:
    _require(workspace, name)
    record = proposals.load(name)
    if record is None:
        raise ProposalMissingError(name)
    return ListingAiInputs.read(workspace, name).judge(record)


@dataclass(frozen=True)
class ProposalResolution:
    """Sections to record on the proposal generated at ``generated_at``:
    each resolved, reopened (``pending``), or ``None`` to leave it as it is."""

    generated_at: datetime
    title: Resolution | None = None
    tags: Resolution | None = None
    lead: Resolution | None = None


def resolve_proposal(
    workspace: Workspace,
    proposals: ProposalStore,
    name: str,
    resolution: ProposalResolution,
) -> ListingProposal:
    """Record ``resolution``'s sections on the proposal it names, and answer
    it as :func:`read_proposal` would.

    Under the listing's write lock, re-checking the listing inside it, so a
    delete or rename cannot land between the read and the write and leave a
    record behind for a listing that is gone. Refusals, with nothing
    recorded: :class:`ListingMissingError` (also after waiting for the lock),
    :class:`ProposalMissingError`, and :class:`ProposalReplacedError` when the proposal
    has been regenerated since.
    """
    _require(workspace, name)
    with ListingDocuments(workspace).lock(name):
        _require(workspace, name)
        try:
            record = proposals.resolve(
                name,
                generated_at=resolution.generated_at,
                title=resolution.title,
                tags=resolution.tags,
                lead=resolution.lead,
            )
        except CachedProposalReplacedError as exc:
            raise ProposalReplacedError(name) from exc
    if record is None:
        raise ProposalMissingError(name)
    return ListingAiInputs.read(workspace, name).judge(record)


def _require(workspace: Workspace, name: str) -> None:
    if not ListingDocuments(workspace).exists(name):
        raise ListingMissingError(name)
