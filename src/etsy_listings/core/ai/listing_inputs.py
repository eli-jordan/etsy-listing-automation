"""Saved-listing facts shared by AI generation and proposal judgment.

A prepared request carries the comparison snapshot derived from exactly
those same facts. HTTP adapters choose status codes; invalid workspace refs
remain actionable errors on a background run. Reading again between run
steps is deliberate, not one frozen snapshot for the whole run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from etsy_listings.core.ai.models import GarmentContext, SeoRequest
from etsy_listings.core.ai.proposals import (
    ListingProposal,
    ProposalRecord,
    SeoProposalSnapshot,
    proposal_staleness,
)
from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.workspace.facts import WorkspaceFacts
from etsy_listings.core.workspace.listing_documents import ListingDocuments
from etsy_listings.core.workspace.workspace import Workspace

_PREFERRED_DESIGN_KEYS = ("default", "on-light", "on-dark")
# one image for AI, not a per-colour render; unfamiliar keys sort
# alphabetically so a reordered mapping never changes the chosen image.


@dataclass(frozen=True)
class PreparedSeo:
    request: SeoRequest
    snapshot: SeoProposalSnapshot


@dataclass(frozen=True)
class ListingAiInputs:
    snapshot: SeoProposalSnapshot
    _workspace: Workspace
    _name: str
    _has_profile: bool

    @classmethod
    def read(
        cls, workspace: Workspace, name: str, *, facts: WorkspaceFacts | None = None
    ) -> ListingAiInputs:
        if not ListingDocuments(workspace).exists(name):
            raise UserFacingError(f"the listing {name!r} no longer exists")
        listing = workspace.load_listing(name)
        facts = facts or WorkspaceFacts.gather(workspace)
        profile = facts.garment_profile(listing.garment_profile)
        blueprint = profile.blueprint if profile is not None else None
        snapshot = SeoProposalSnapshot(
            brief=listing.brief,
            product_type=blueprint.display_title if blueprint is not None else "",
            etsy_category=listing.etsy.section or "",
            materials=list(profile.materials) if profile is not None else [],
            colors=list(listing.colors),
            garment_brand=blueprint.brand if blueprint is not None else "",
            garment_model=blueprint.model if blueprint is not None else "",
            garment_profile=listing.garment_profile,
            design=dict(listing.design),
            design_content_hash=workspace.design_content_hash(
                listing.design, listing_dir=workspace.listing_dir(name)
            ),
        )
        return cls(snapshot, workspace, name, profile is not None)

    def prepare(self, *, market_block: str = "") -> PreparedSeo:
        """A request and its frozen comparison inputs, from one interpretation."""
        if not self._has_profile:
            raise UserFacingError("the listing has no usable garment profile")
        snapshot = self.snapshot
        if not snapshot.design:
            raise UserFacingError("the listing has no selected design")
        key = next(
            (key for key in _PREFERRED_DESIGN_KEYS if key in snapshot.design),
            min(snapshot.design),
        )
        design: Path = self._workspace.resolve_ref(
            snapshot.design[key], listing_dir=self._workspace.listing_dir(self._name)
        )
        request = SeoRequest(
            market_block=market_block,
            brief=snapshot.brief,
            product_type=snapshot.product_type,
            etsy_category=snapshot.etsy_category,
            materials=tuple(snapshot.materials),
            colors=tuple(snapshot.colors),
            garment=GarmentContext(brand=snapshot.garment_brand, model=snapshot.garment_model),
            design_image=design,
        )
        return PreparedSeo(request, snapshot)

    def judge(self, record: ProposalRecord) -> ListingProposal:
        """Missing profile facts still make a cached proposal stale, not unreadable."""
        return ListingProposal(
            proposal=record.proposal,
            snapshot=record.snapshot,
            generated_at=record.generated_at,
            origin=record.origin,
            resolution=record.resolution,
            stale=proposal_staleness(record.snapshot, self.snapshot),
        )
