"""A listing's cached AI proposal, as the editor reads and resolves it
(ADR-0049; spec, *Durable AI proposals*).

One proposal per listing, written by every AI run before it announces it
(``runner.py``) and kept in ``.cache/proposals/`` by ``ai/proposals.py``'s
store. Reading judges it against the saved listing every time -- staleness is
never stored, and a stale proposal stays usable. Resolving records that the
seller accepted, dismissed or reopened a section; the chosen value itself
reaches ``listing.yaml`` through ordinary autosave. Neither clears it: only a
replacement, the listing's deletion, a fully successful apply (ADR-0050) or
clearing the cache does.
"""

from __future__ import annotations

from datetime import datetime

from etsy_listings.core.ai.listing_inputs import ListingAiInputs
from etsy_listings.core.ai.proposals import (
    ListingProposal,
    ProposalReplacedError,
    ProposalStore,
    Resolution,
)
from etsy_listings.core.application.refusals import (
    ListingMissing,
    ProposalMissing,
    ProposalReplaced,
)
from etsy_listings.core.workspace.listing_documents import ListingDocuments
from etsy_listings.core.workspace.workspace import Workspace


def read_proposal(workspace: Workspace, proposals: ProposalStore, name: str) -> ListingProposal:
    """Listing ``name``'s proposal, judged stale or not against the listing
    as saved now. :class:`ListingMissing`, or :class:`ProposalMissing` when
    none is cached."""
    _require(workspace, name)
    record = proposals.load(name)
    if record is None:
        raise ProposalMissing(name)
    return ListingAiInputs.read(workspace, name).judge(record)


def resolve_proposal(
    workspace: Workspace,
    proposals: ProposalStore,
    name: str,
    *,
    generated_at: datetime,
    title: Resolution | None = None,
    tags: Resolution | None = None,
    lead: Resolution | None = None,
) -> ListingProposal:
    """Record the given sections as resolved (or reopened, ``pending``) on
    the proposal generated at ``generated_at``, and answer it as
    :func:`read_proposal` would.

    Under the listing's write lock, re-checking the listing inside it, so a
    delete or rename cannot land between the read and the write and leave a
    record behind for a listing that is gone. Refusals, with nothing
    recorded: :class:`ListingMissing` (also after waiting for the lock),
    :class:`ProposalMissing`, and :class:`ProposalReplaced` when the proposal
    has been regenerated since.
    """
    _require(workspace, name)
    with ListingDocuments(workspace).lock(name):
        _require(workspace, name)
        try:
            record = proposals.resolve(
                name, generated_at=generated_at, title=title, tags=tags, lead=lead
            )
        except ProposalReplacedError as exc:
            raise ProposalReplaced(name) from exc
    if record is None:
        raise ProposalMissing(name)
    return ListingAiInputs.read(workspace, name).judge(record)


def _require(workspace: Workspace, name: str) -> None:
    if not ListingDocuments(workspace).exists(name):
        raise ListingMissing(name)
