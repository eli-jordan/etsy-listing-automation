"""The latest AI SEO proposal per listing, kept in server cache (A41; spec,
*Durable AI proposals*; PRD 4 and 71 as amended by PRD 74).

``.cache/proposals/<listing>.json`` holds one record per listing:
the ranked choices, the inputs frozen when they were generated, when, which
run origin wrote it, and which of its three sections the seller has accepted
or dismissed. Regeneration replaces it; there is no history and no expiry.
It goes when the listing is deleted or fully applied, or ``.cache`` is
cleared, and moves when the listing is renamed (A42).

It lives here rather than beside the UI so the engine can reach it (A44's
cleanup after a full apply) without importing ``ui``.

:func:`proposal_staleness` is the one answer to "does this proposal still
describe its listing?". It was the browser's (``aiSeoStorage.isStale``),
which meant the batch summary could not ask it; on the server the editor and
the summary read the same reasons.
"""

from __future__ import annotations

import json
import threading
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from etsy_listings.ai.models import SeoProposal
from etsy_listings.workspace.atomic import read_bytes_retrying, write_json_atomic
from etsy_listings.workspace.workspace import Workspace

SCHEMA = 1

SeoRationaleIntent = Literal["core_product", "bottom_of_funnel", "style"]
SeoRationaleField = Literal["title", "tags", "description_lead"]
SeoWarningKind = Literal["general", "trademark"]


class SeoRationaleEntry(BaseModel):
    """One of the proposal's seven priority-phrase rationales -- the wire
    shape of `ai/models.py.PhraseRationale`."""

    phrase: str
    intent: SeoRationaleIntent
    reason: str
    used_in: list[SeoRationaleField]


class SeoWarningEntry(BaseModel):
    """The wire shape of `ai/models.py.ProposalWarning`."""

    message: str
    kind: SeoWarningKind = "general"


class SeoProposalSnapshot(BaseModel):
    """The generation inputs, frozen before the provider starts: everything
    `ai/models.py.SeoRequest` sent except the design image itself, plus the
    design's identity and content hash. :func:`proposal_staleness` compares
    one of these against the same inputs read from the listing now."""

    brief: str
    product_type: str
    etsy_category: str
    materials: list[str]
    colors: list[str]
    garment_brand: str
    garment_model: str
    garment_profile: str
    design: dict[str, str]
    design_content_hash: str | None


class ProposalChoices(BaseModel):
    """What the seller chooses from: the validated `ai/models.py.SeoProposal`,
    field for field, as JSON can carry it."""

    titles: list[str]
    tags: list[str]
    description_leads: list[str]
    rationale: list[SeoRationaleEntry]
    warnings: list[SeoWarningEntry]
    observed_text: str

    @classmethod
    def of(cls, proposal: SeoProposal) -> ProposalChoices:
        return cls(
            titles=list(proposal.titles),
            tags=list(proposal.tags),
            description_leads=list(proposal.description_leads),
            rationale=[
                SeoRationaleEntry(
                    phrase=entry.phrase,
                    intent=entry.intent,
                    reason=entry.reason,
                    used_in=list(entry.used_in),
                )
                for entry in proposal.rationale
            ],
            warnings=[
                SeoWarningEntry(message=warning.message, kind=warning.kind)
                for warning in proposal.warnings
            ],
            observed_text=proposal.observed_text,
        )


Resolution = Literal["pending", "accepted", "dismissed"]
ProposalOrigin = Literal["manual", "batch"]


class ProposalResolution(BaseModel):
    """Each section's state (spec, *Durable AI proposals*): a section the
    seller accepted or dismissed stays resolved after a reload, so its drawer
    does not present itself as new again. ``pending`` is still open."""

    title: Resolution = "pending"
    tags: Resolution = "pending"
    lead: Resolution = "pending"


class ProposalRecord(BaseModel):
    """``.cache/proposals/<listing>.json`` (A41)."""

    model_config = ConfigDict(populate_by_name=True)

    schema_version: int = Field(SCHEMA, alias="schema")
    listing: str
    """The listing that wrote it. On a case-insensitive filesystem another
    spelling of the name opens the same file; this is what tells them apart."""
    proposal: ProposalChoices
    snapshot: SeoProposalSnapshot
    generated_at: datetime
    origin: ProposalOrigin
    resolution: ProposalResolution = Field(default_factory=ProposalResolution)


class ProposalReplacedError(Exception):
    """A resolution named a proposal that has since been regenerated."""


_GUARD = threading.Lock()
_LOCKS: dict[tuple[str, str], threading.Lock] = {}
"""Every record's lock in this process, keyed by the resolved proposals
directory and the casefolded listing name. Process-wide, not per store:
the engine removes a fully applied listing's proposal through a store of
its own (A44) while the UI's store may be resolving the same record, and
two sets of locks would let the remove land inside that read-modify-write
and be written back over."""


class ProposalStore:
    """The one reader and writer of proposal records. Every mutation is a
    read-modify-write under the record's lock (A37), and every store over
    one workspace shares those locks, so a store is cheap to make."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    @contextmanager
    def _lock(self, *listings: str) -> Iterator[None]:
        """Every named record's lock, taken in sorted order so two moves in
        opposite directions cannot deadlock. Keyed by casefold, as the
        listing write locks are, so two spellings that may be one file on
        disk are never written at once."""
        directory = str(self._workspace.proposal_file(listings[0]).parent.resolve())
        with ExitStack() as stack:
            for name in sorted({name.casefold() for name in listings}):
                with _GUARD:
                    lock = _LOCKS.setdefault((directory, name), threading.Lock())
                stack.enter_context(lock)
            yield

    def load(self, listing: str) -> ProposalRecord | None:
        """``listing``'s proposal, or ``None`` for none -- and for a record
        this code cannot read, or one another listing's name wrote."""
        try:
            path = self._workspace.proposal_file(listing)
            raw = json.loads(read_bytes_retrying(path).decode("utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
            return None
        try:
            record = ProposalRecord.model_validate(raw)
        except ValidationError:
            return None
        return record if record.listing == listing else None

    def _save(self, record: ProposalRecord) -> None:
        write_json_atomic(
            self._workspace.proposal_file(record.listing),
            record.model_dump(mode="json", by_alias=True),
        )

    def put(
        self,
        listing: str,
        choices: ProposalChoices,
        snapshot: SeoProposalSnapshot,
        *,
        generated_at: datetime,
        origin: ProposalOrigin,
    ) -> ProposalRecord:
        """Replace ``listing``'s proposal with a new one, every section open."""
        record = ProposalRecord(
            listing=listing,
            proposal=choices,
            snapshot=snapshot,
            generated_at=generated_at,
            origin=origin,
        )
        with self._lock(listing):
            self._save(record)
        return record

    def resolve(
        self,
        listing: str,
        *,
        generated_at: datetime,
        title: Resolution | None = None,
        tags: Resolution | None = None,
        lead: Resolution | None = None,
    ) -> ProposalRecord | None:
        """Record sections as resolved (or reopened) on the proposal
        generated at ``generated_at``. ``None`` when there is no proposal;
        :class:`ProposalReplacedError` when it is no longer that one."""
        with self._lock(listing):
            record = self.load(listing)
            if record is None:
                return None
            if record.generated_at != generated_at:
                raise ProposalReplacedError(listing)
            changed = {
                key: value
                for key, value in (("title", title), ("tags", tags), ("lead", lead))
                if value is not None
            }
            resolution = record.resolution.model_copy(update=changed)
            record = record.model_copy(update={"resolution": resolution})
            self._save(record)
            return record

    def move(self, old: str, new: str) -> None:
        """Rename's half of A42: the record follows the listing."""
        with self._lock(old, new):
            record = self.load(old)
            if record is None:
                return
            # Unlink first: on a case-insensitive filesystem a case-only
            # rename's two paths are one file, which a later unlink would
            # delete straight after writing it.
            self._workspace.proposal_file(old).unlink(missing_ok=True)
            self._save(record.model_copy(update={"listing": new}))

    def remove(self, listing: str) -> None:
        """Delete's half of A42, and A44's cleanup after a full apply."""
        with self._lock(listing):
            if self.load(listing) is not None:
                self._workspace.proposal_file(listing).unlink(missing_ok=True)


class ProposalStaleness(BaseModel):
    is_stale: bool
    reasons: list[str]
    """One per input that moved, in a fixed order, each finishing the
    drawer heading's *Out of date: {reason}. Still usable* (UI doc §8)."""


class ListingProposal(BaseModel):
    """A listing's cached proposal as the editor and the batch summary read
    it (A41): the record, and whether it still describes the saved listing.
    ``stale`` is computed from the saved listing on every read, never
    stored."""

    proposal: ProposalChoices
    snapshot: SeoProposalSnapshot
    generated_at: datetime
    origin: ProposalOrigin
    resolution: ProposalResolution
    stale: ProposalStaleness


def _same_set(frozen: Sequence[str], now: Sequence[str]) -> bool:
    """Order carries no meaning -- ``VariantsTab`` appends a re-enabled colour
    at the end -- but a repeat does, so a multiset, not a set."""
    return Counter(frozen) == Counter(now)


def proposal_staleness(frozen: SeoProposalSnapshot, now: SeoProposalSnapshot) -> ProposalStaleness:
    """Which generation inputs changed between ``frozen`` and ``now`` (A41).

    Ported field by field from the frontend's ``isStale``. Two echoes are
    folded into the change that caused them, so the heading names what the
    seller did: a different garment profile brings its own product type,
    materials, brand and model, and a different design its own file hash.
    Those facts are reported alone only when they moved under an unchanged
    name -- the profile file or the artwork was edited in place.
    """
    reasons: list[str] = []
    if frozen.brief != now.brief:
        reasons.append("brief edited since")
    if frozen.etsy_category != now.etsy_category:
        reasons.append("shop section changed since")
    if not _same_set(frozen.colors, now.colors):
        reasons.append("colours changed since")
    if frozen.garment_profile != now.garment_profile:
        reasons.append("garment profile changed since")
    else:
        if not _same_set(frozen.materials, now.materials):
            reasons.append("materials changed since")
        if frozen.product_type != now.product_type:
            reasons.append("product type changed since")
        if frozen.garment_brand != now.garment_brand:
            reasons.append("garment brand changed since")
        if frozen.garment_model != now.garment_model:
            reasons.append("garment model changed since")
    if frozen.design != now.design:
        reasons.append("design changed since")
    elif frozen.design_content_hash != now.design_content_hash:
        reasons.append("design file edited since")
    return ProposalStaleness(is_stale=bool(reasons), reasons=reasons)
