import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ListingDetail, SeoProposalResponse } from "../../../types";
import {
  buildComparableSnapshot,
  clearStoredProposal,
  isStale,
  loadStoredProposal,
  saveStoredProposal,
  toStoredProposal,
  updateUnresolved,
} from "./aiSeoStorage";

function detail(over: Partial<ListingDetail> = {}): ListingDetail {
  return {
    garment_profile: "comfort-colors-1717",
    design: { default: "designs/take-a-hike.png" },
    colors: ["black"],
    brief: "A relaxed hiking tee.",
    garment_materials: ["ring-spun cotton"],
    garment_product_type: "tee",
    garment_brand: "Comfort Colors",
    garment_model: "1717",
    prices: {},
    price_overrides: {},
    artwork: {},
    pricing_plan: null,
    etsy: {
      title: "",
      description: { lead: "", text: null, ref: null },
      tags: [],
      variation_images: null,
      renewal: null,
      section: "Graphic Tees",
      shipping_profile: null,
    },
    media: [],
    name: "take-a-hike",
    modified_at: "2026-09-17T10:00:00Z",
    status: "draft",
    issues: [],
    field_errors: {},
    etsy_listing_id: null,
    printify_product_id: null,
    pricing_plan_name: null,
    resolved_prices: [],
    description_composed: "",
    design_content_hash: null,
    ...over,
  };
}

function proposal(over: Partial<SeoProposalResponse> = {}): SeoProposalResponse {
  return {
    titles: ["Title A", "Title B", "Title C"],
    tags: Array.from({ length: 20 }, (_, i) => `tag-${i}`),
    description_leads: ["Lead A", "Lead B", "Lead C"],
    rationale: [],
    warnings: [],
    observed_text: "",
    snapshot: {
      brief: "A relaxed hiking tee.",
      product_type: "tee",
      etsy_category: "Graphic Tees",
      materials: ["ring-spun cotton"],
      colors: ["black"],
      garment_brand: "Comfort Colors",
      garment_model: "1717",
      garment_profile: "comfort-colors-1717",
      design: { default: "designs/take-a-hike.png" },
      design_content_hash: null,
    },
    // Relative to now, not a fixed date: the server stamps `expires_at` a day
    // out (`ui/api/seo.py._PROPOSAL_TTL`) and `loadStoredProposal` discards
    // anything past it -- so a hard-coded pair is a fixture that silently
    // becomes "expired" on a particular morning, which is exactly what it did.
    generated_at: new Date(Date.now() - 60_000).toISOString(),
    expires_at: new Date(Date.now() + 86_400_000).toISOString(),
    ...over,
  };
}

const scope = { workspace: "workspace-1", listing: "take-a-hike" };

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
  localStorage.clear();
});

describe("buildComparableSnapshot", () => {
  it("reads the fields the server snapshot can be compared against", () => {
    expect(buildComparableSnapshot(detail())).toEqual({
      brief: "A relaxed hiking tee.",
      colors: ["black"],
      etsy_category: "Graphic Tees",
      materials: ["ring-spun cotton"],
      garment_profile: "comfort-colors-1717",
      product_type: "tee",
      garment_brand: "Comfort Colors",
      garment_model: "1717",
      design: JSON.stringify([["default", "designs/take-a-hike.png"]]),
      design_content_hash: null,
    });
  });

  it("treats a listing with no section and no materials as empty strings/lists", () => {
    const snap = buildComparableSnapshot(
      detail({ etsy: { ...detail().etsy, section: null }, garment_materials: null }),
    );
    expect(snap.etsy_category).toBe("");
    expect(snap.materials).toEqual([]);
  });
});

describe("isStale", () => {
  it("is false when nothing relevant has changed since generation", () => {
    const stored = toStoredProposal(proposal());
    expect(isStale(stored, detail())).toBe(false);
  });

  it("is true once the brief changes", () => {
    const stored = toStoredProposal(proposal());
    expect(isStale(stored, detail({ brief: "A different brief." }))).toBe(true);
  });

  it("is true once the selected design changes", () => {
    const stored = toStoredProposal(proposal());
    expect(isStale(stored, detail({ design: { default: "designs/other.png" } }))).toBe(true);
  });

  it("is true when design bytes change at the same reference", () => {
    const stored = toStoredProposal(proposal());
    expect(isStale(stored, detail({ design_content_hash: "new-content" }))).toBe(true);
  });

  it("is true once the garment profile changes", () => {
    const stored = toStoredProposal(proposal());
    expect(isStale(stored, detail({ garment_profile: "other-profile" }))).toBe(true);
  });

  it("is true when a profile blueprint changes under the same profile name", () => {
    const stored = toStoredProposal(proposal());
    expect(isStale(stored, detail({ garment_product_type: "long sleeve tee" }))).toBe(true);
    expect(isStale(stored, detail({ garment_brand: "Other Brand" }))).toBe(true);
    expect(isStale(stored, detail({ garment_model: "2000" }))).toBe(true);
  });

  it("is true once colors change", () => {
    const stored = toStoredProposal(proposal());
    expect(isStale(stored, detail({ colors: ["black", "white"] }))).toBe(true);
  });

  it("is true once materials change", () => {
    const stored = toStoredProposal(proposal());
    expect(isStale(stored, detail({ garment_materials: ["organic cotton"] }))).toBe(true);
  });

  it("is true once the Etsy section changes", () => {
    const stored = toStoredProposal(proposal());
    expect(isStale(stored, detail({ etsy: { ...detail().etsy, section: "Outdoor Gifts" } }))).toBe(
      true,
    );
  });

  it("is false for an unrelated field change (title text)", () => {
    const stored = toStoredProposal(proposal());
    expect(isStale(stored, detail({ etsy: { ...detail().etsy, title: "Take A Hike Tee" } }))).toBe(
      false,
    );
  });

  it("is false when colors revisit the same set in a different order", () => {
    // `VariantsTab.setColours` appends a re-enabled colour to the end of the
    // array rather than restoring its old position, so toggling a colour off
    // and back on reorders `colors` without changing what is actually
    // selected -- that must not read as a submitted-input change.
    const stored = toStoredProposal(
      proposal({ snapshot: { ...proposal().snapshot, colors: ["black", "white"] } }),
    );
    expect(isStale(stored, detail({ colors: ["white", "black"] }))).toBe(false);
  });
});

describe("localStorage persistence", () => {
  it("returns null when nothing is stored", () => {
    expect(loadStoredProposal(scope)).toBeNull();
  });

  it("round-trips a saved proposal", () => {
    const stored = toStoredProposal(proposal());
    saveStoredProposal(scope, stored);
    expect(loadStoredProposal(scope)).toEqual(stored);
  });

  it("scopes storage by workspace and listing independently", () => {
    const stored = toStoredProposal(proposal());
    saveStoredProposal(scope, stored);
    expect(loadStoredProposal({ workspace: "workspace-2", listing: "take-a-hike" })).toBeNull();
    expect(loadStoredProposal({ workspace: "workspace-1", listing: "other-listing" })).toBeNull();
  });

  it("discards and returns null once the proposal has expired", () => {
    const stored = toStoredProposal(proposal({ expires_at: "2020-01-01T00:00:00Z" }));
    saveStoredProposal(scope, stored);
    expect(loadStoredProposal(scope)).toBeNull();
    // The expired entry is actually removed, not just ignored.
    expect(localStorage.length).toBe(0);
  });

  it("returns null for malformed JSON instead of throwing", () => {
    localStorage.setItem("ai-seo-proposal:workspace-1:take-a-hike", "{not json");
    expect(loadStoredProposal(scope)).toBeNull();
  });

  it("clearStoredProposal removes the entry", () => {
    const stored = toStoredProposal(proposal());
    saveStoredProposal(scope, stored);
    clearStoredProposal(scope);
    expect(loadStoredProposal(scope)).toBeNull();
  });
});

describe("toStoredProposal", () => {
  it("starts every field unresolved", () => {
    const stored = toStoredProposal(proposal());
    expect(stored.unresolved).toEqual({ title: true, tags: true, lead: true });
  });
});

describe("updateUnresolved", () => {
  it("clears only the named field and keeps the others open", () => {
    const stored = toStoredProposal(proposal());
    saveStoredProposal(scope, stored);

    const next = updateUnresolved(scope, { title: false });

    expect(next?.unresolved).toEqual({ title: false, tags: true, lead: true });
    expect(loadStoredProposal(scope)?.unresolved).toEqual({
      title: false,
      tags: true,
      lead: true,
    });
  });

  it("removes the stored proposal once every field is resolved", () => {
    const stored = toStoredProposal(proposal());
    saveStoredProposal(scope, stored);

    updateUnresolved(scope, { title: false });
    updateUnresolved(scope, { tags: false });
    const last = updateUnresolved(scope, { lead: false });

    expect(last).toBeNull();
    expect(loadStoredProposal(scope)).toBeNull();
  });

  it("returns null and does nothing when there is no stored proposal", () => {
    expect(updateUnresolved(scope, { title: false })).toBeNull();
  });
});
