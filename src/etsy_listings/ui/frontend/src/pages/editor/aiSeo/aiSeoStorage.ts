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

export interface StoredAiSeoProposal {
  proposal: SeoProposalResponse;
  unresolved: AiSeoUnresolved;
}

export interface AiSeoStorageScope {
  /** Opaque `WorkspaceSummary.storage_id`, independent of shop name (PRD 4). */
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

/** Read the editor's current generation inputs for comparison with the saved
 * inputs the server captured before it started generation. */
export function buildComparableSnapshot(detail: ListingDetail): {
  brief: string;
  colors: string[];
  etsy_category: string;
  materials: string[];
  garment_profile: string;
  product_type: string | null;
  garment_brand: string | null;
  garment_model: string | null;
  design: string;
  design_content_hash: string | null;
} {
  return {
    brief: detail.brief,
    colors: detail.colors,
    etsy_category: detail.etsy.section ?? "",
    materials: detail.garment_materials ?? [],
    garment_profile: detail.garment_profile,
    product_type: detail.garment_product_type ?? null,
    garment_brand: detail.garment_brand ?? null,
    garment_model: detail.garment_model ?? null,
    design: designIdentity(detail.design),
    design_content_hash: detail.design_content_hash ?? null,
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

/** Open every drawer for a response carrying its own frozen input snapshot. */
export function toStoredProposal(proposal: SeoProposalResponse): StoredAiSeoProposal {
  return {
    proposal,
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
    current.garment_profile !== snapshot.garment_profile ||
    current.product_type !== snapshot.product_type ||
    current.garment_brand !== snapshot.garment_brand ||
    current.garment_model !== snapshot.garment_model ||
    current.design !== designIdentity(snapshot.design) ||
    current.design_content_hash !== snapshot.design_content_hash
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
    const snapshot = (record.proposal as Record<string, unknown>).snapshot;
    if (typeof snapshot !== "object" || snapshot === null) return null;
    const inputs = snapshot as Record<string, unknown>;
    if (typeof inputs.garment_profile !== "string") return null;
    if (typeof inputs.design !== "object" || inputs.design === null) return null;
    if (typeof inputs.design_content_hash !== "string" && inputs.design_content_hash !== null)
      return null;
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
