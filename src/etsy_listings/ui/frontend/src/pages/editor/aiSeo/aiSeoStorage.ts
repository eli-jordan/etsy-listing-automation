import type { ListingDetail, SeoProposalResponse } from "../../../types";

/**
 * Browser-local persistence for one listing's pending AI Mode proposal (AI
 * SEO implementation plan, PR7 item 3, and the settled "Proposal
 * persistence" decision): kept only in `localStorage`, scoped to the
 * workspace and the saved listing, for the one day the server itself already
 * commits to via `SeoProposalResponse.expires_at` (`ui/api/seo.py`'s
 * `_PROPOSAL_TTL`) -- this module trusts that timestamp rather than
 * recomputing its own retention window from a client clock alone.
 *
 * Never written to a workspace file and never sent back to the server; it is
 * exactly what item 3 calls "browser local storage", nothing more.
 */

/** Which of the proposal's three independent choices are still open. All
 * three start `true` (implementation plan, "Proposal and stale-state
 * rules"); a suggestion drawer that fully resolves (a choice is made, or the
 * seller closes/rejects it) sets its own flag `false`, and once every flag is
 * `false` the whole entry is removed (`docs/ui-listing-seo-interactions.md`
 * section 7: "Resolve or dismiss all drawers: Remove the pending proposal
 * from local storage."). */
export interface AiSeoUnresolved {
  title: boolean;
  tags: boolean;
  lead: boolean;
}

/** The submitted-inputs snapshot fields the frontend can observe on its own,
 * beside what `SeoProposalResponse.snapshot` already echoes back.
 *
 * `garmentProfile` stands in for the snapshot's `garment_brand`/
 * `garment_model`/`product_type`: none of the three is exposed anywhere in
 * `ListingDetail` or `GarmentProfileSummary` (both are resolved server-side
 * from the garment profile's blueprint, which the frontend never loads), but
 * all three are pure functions of *which* profile is selected -- so tracking
 * the profile id catches every case those fields would actually change,
 * without fetching blueprint internals the editor has no other use for.
 *
 * `design` stands in for the plan's "selected design identity/content hash":
 * `SeoRequest`'s own docstring calls that deliberately the browser's
 * bookkeeping, not a fact the API computes, so this module snapshots the
 * listing's own `design` map (already the browser's copy of that identity)
 * as a stable JSON string rather than hashing image bytes it would have to
 * fetch specially. */
export interface AiSeoExtraSnapshot {
  garmentProfile: string;
  design: string;
}

export interface StoredAiSeoProposal {
  proposal: SeoProposalResponse;
  extra: AiSeoExtraSnapshot;
  unresolved: AiSeoUnresolved;
}

export interface AiSeoStorageScope {
  /** `WorkspaceSummary.shop_name`, or a fixed fallback for a workspace that
   * has none configured yet -- the one workspace-identifying fact the
   * frontend can read (`getWorkspace()`); see the module docstring on
   * `useAiSeoMode.ts` for why nothing more specific exists to scope by. */
  workspace: string;
  listing: string;
}

const STORAGE_PREFIX = "ai-seo-proposal";

function storageKey(scope: AiSeoStorageScope): string {
  return `${STORAGE_PREFIX}:${scope.workspace}:${scope.listing}`;
}

/** A stable, order-independent identity for `ListingDetail.design`: sorted so
 * that two listings that resolved to the same artwork map through a
 * different key insertion order (an unlikely but not-impossible outcome of
 * `config/listing.py`'s coercion) still compare equal. */
function designIdentity(design: Record<string, string>): string {
  return JSON.stringify(Object.entries(design).sort(([a], [b]) => a.localeCompare(b)));
}

/** The generation-input fields of a listing, in the same shape
 * `SeoProposalSnapshot` uses for the fields the server itself can echo, plus
 * `garmentProfile`/`design` for the two it cannot (see `AiSeoExtraSnapshot`).
 * Reads straight off `ListingDetail` -- never a second network call -- so a
 * staleness check never disagrees with what the editor is showing right now. */
export function buildComparableSnapshot(detail: ListingDetail): {
  brief: string;
  colors: string[];
  etsy_category: string;
  materials: string[];
  garmentProfile: string;
  design: string;
} {
  return {
    brief: detail.brief,
    colors: detail.colors,
    etsy_category: detail.etsy.section ?? "",
    materials: detail.garment_materials ?? [],
    garmentProfile: detail.garment_profile,
    design: designIdentity(detail.design),
  };
}

/** Order-independent content equality: `colors` can revisit the same set
 * through a different order without any real change (`VariantsTab.setColours`
 * appends a re-enabled colour to the end rather than restoring its old
 * position), and the submitted generation input is a JSON list whose order
 * carries no meaning to the model either. Mirrors `designIdentity`'s own
 * sort-before-compare reasoning just above. */
function sameStrings(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const sortedA = [...a].sort();
  const sortedB = [...b].sort();
  return sortedA.every((value, index) => value === sortedB[index]);
}

/** Builds a fresh `StoredAiSeoProposal` for a proposal the server just
 * returned, snapshotting the two extra fields it did not (see
 * `AiSeoExtraSnapshot`) and opening every drawer. */
export function toStoredProposal(
  proposal: SeoProposalResponse,
  detail: ListingDetail,
): StoredAiSeoProposal {
  const comparable = buildComparableSnapshot(detail);
  return {
    proposal,
    extra: { garmentProfile: comparable.garmentProfile, design: comparable.design },
    unresolved: { title: true, tags: true, lead: true },
  };
}

/** Whether `stored`'s choices are still trustworthy against `detail`'s
 * current values (implementation plan, "Proposal and stale-state rules"):
 * `true` the moment any submitted generation input has moved since the
 * request that produced `stored.proposal`. Prompt-file edits, unrelated
 * workspace edits, and other listings never reach this function at all --
 * only fields this listing's editor actually holds are compared. */
export function isStale(stored: StoredAiSeoProposal, detail: ListingDetail): boolean {
  const current = buildComparableSnapshot(detail);
  const snapshot = stored.proposal.snapshot;
  return (
    current.brief !== snapshot.brief ||
    current.etsy_category !== snapshot.etsy_category ||
    !sameStrings(current.colors, snapshot.colors) ||
    !sameStrings(current.materials, snapshot.materials) ||
    current.garmentProfile !== stored.extra.garmentProfile ||
    current.design !== stored.extra.design
  );
}

function isAiSeoUnresolved(value: unknown): value is AiSeoUnresolved {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.title === "boolean" &&
    typeof record.tags === "boolean" &&
    typeof record.lead === "boolean"
  );
}

/** A defensive parse, not a trusting `JSON.parse` cast: this reads back
 * whatever a *previous* version of this module (or a corrupted browser
 * profile) wrote, so a shape it does not recognise is treated exactly like
 * "nothing stored" rather than thrown from a render. */
function parseStored(raw: string): StoredAiSeoProposal | null {
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (typeof parsed !== "object" || parsed === null) return null;
    const record = parsed as Record<string, unknown>;
    if (typeof record.proposal !== "object" || record.proposal === null) return null;
    if (typeof record.extra !== "object" || record.extra === null) return null;
    if (!isAiSeoUnresolved(record.unresolved)) return null;
    return record as unknown as StoredAiSeoProposal;
  } catch {
    return null;
  }
}

function isExpired(stored: StoredAiSeoProposal): boolean {
  const expiresAt = Date.parse(stored.proposal.expires_at);
  return Number.isNaN(expiresAt) || Date.now() >= expiresAt;
}

/** The current pending proposal for this listing, or `null` when there is
 * none -- because nothing was ever stored, the stored JSON is not a shape
 * this module recognises, or the one-day window
 * (`SeoProposalResponse.expires_at`) has passed. An expired entry is removed
 * as a side effect (item 3: "discard expired ones"), so the next call (and
 * every other tab open on this listing) sees the same "nothing pending"
 * answer rather than re-discovering the same stale row. */
export function loadStoredProposal(scope: AiSeoStorageScope): StoredAiSeoProposal | null {
  const raw = localStorage.getItem(storageKey(scope));
  if (raw === null) return null;
  const stored = parseStored(raw);
  if (stored === null || isExpired(stored)) {
    localStorage.removeItem(storageKey(scope));
    return null;
  }
  return stored;
}

export function saveStoredProposal(scope: AiSeoStorageScope, stored: StoredAiSeoProposal): void {
  localStorage.setItem(storageKey(scope), JSON.stringify(stored));
}

export function clearStoredProposal(scope: AiSeoStorageScope): void {
  localStorage.removeItem(storageKey(scope));
}

/** Applies a resolution to one or more drawers (`docs/ui-listing-seo-
 * interactions.md` section 7: "Resolve or dismiss one drawer: Clear only
 * that part of the pending proposal."), and removes the whole stored entry
 * once every flag is `false` ("Resolve or dismiss all drawers: Remove the
 * pending proposal from local storage."). Returns the updated entry, or
 * `null` when it was just removed (all resolved) or there was nothing stored
 * to update in the first place. */
export function updateUnresolved(
  scope: AiSeoStorageScope,
  patch: Partial<AiSeoUnresolved>,
): StoredAiSeoProposal | null {
  const stored = loadStoredProposal(scope);
  if (stored === null) return null;
  const unresolved = { ...stored.unresolved, ...patch };
  if (!unresolved.title && !unresolved.tags && !unresolved.lead) {
    clearStoredProposal(scope);
    return null;
  }
  const next: StoredAiSeoProposal = { ...stored, unresolved };
  saveStoredProposal(scope, next);
  return next;
}
