import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { getSeoReadiness, requestSeoProposal, SeoApiError } from "./seo";
import type { SeoProposalResponse, SeoReadinessResponse } from "../types";

afterEach(() => {
  vi.restoreAllMocks();
});

function proposal(): SeoProposalResponse {
  return {
    titles: ["A", "B", "C"],
    tags: Array.from({ length: 20 }, (_, i) => `tag-${i}`),
    description_leads: ["Lead A", "Lead B", "Lead C"],
    rationale: [],
    warnings: [],
    observed_text: "",
    snapshot: {
      brief: "a brief",
      product_type: "tee",
      etsy_category: "",
      materials: ["cotton"],
      colors: ["black"],
      garment_brand: "Comfort Colors",
      garment_model: "1717",
      garment_profile: "comfort-colors-1717",
      design: { default: "designs/take-a-hike.png" },
      design_content_hash: null,
    },
    generated_at: "2026-09-23T00:00:00Z",
    // Relative to now -- see `aiSeoStorage.test.ts` for why a fixed pair is a
    // fixture with an expiry date of its own.
    expires_at: new Date(Date.now() + 86_400_000).toISOString(),
  };
}

describe("getSeoReadiness", () => {
  it("returns the readiness payload on success", async () => {
    const readiness: SeoReadinessResponse = { ready: true };
    vi.spyOn(api, "GET").mockResolvedValue({
      data: readiness,
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    await expect(getSeoReadiness("take-a-hike")).resolves.toEqual(readiness);
  });

  it("throws SeoApiError when the request fails", async () => {
    vi.spyOn(api, "GET").mockResolvedValue({
      data: undefined,
      error: { detail: "boom" },
      response: new Response(null, { status: 500 }),
    } as never);

    await expect(getSeoReadiness("take-a-hike")).rejects.toBeInstanceOf(SeoApiError);
  });
});

describe("requestSeoProposal", () => {
  it("resolves a success outcome with the proposal", async () => {
    const body = proposal();
    vi.spyOn(api, "POST").mockResolvedValue({
      data: body,
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    const controller = new AbortController();
    await expect(requestSeoProposal("take-a-hike", controller.signal)).resolves.toEqual({
      kind: "success",
      proposal: body,
    });
  });

  it("resolves a failed outcome on a non-2xx response", async () => {
    vi.spyOn(api, "POST").mockResolvedValue({
      data: undefined,
      error: { detail: "no provider is ready" },
      response: new Response(null, { status: 503 }),
    } as never);

    const controller = new AbortController();
    await expect(requestSeoProposal("take-a-hike", controller.signal)).resolves.toEqual({
      kind: "failed",
    });
  });

  it("resolves a failed outcome when the request throws for a non-abort reason", async () => {
    vi.spyOn(api, "POST").mockRejectedValue(new TypeError("network down"));

    const controller = new AbortController();
    await expect(requestSeoProposal("take-a-hike", controller.signal)).resolves.toEqual({
      kind: "failed",
    });
  });

  it("resolves a cancelled outcome when the signal aborts", async () => {
    vi.spyOn(api, "POST").mockImplementation(() => {
      const err = new DOMException("aborted", "AbortError");
      return Promise.reject(err);
    });

    const controller = new AbortController();
    controller.abort();
    await expect(requestSeoProposal("take-a-hike", controller.signal)).resolves.toEqual({
      kind: "cancelled",
    });
  });
});
