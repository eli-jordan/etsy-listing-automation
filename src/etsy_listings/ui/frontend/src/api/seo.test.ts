import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { getListingProposal, getSeoReadiness, resolveListingProposal, SeoApiError } from "./seo";
import { listingProposal } from "../test/aiRuns";
import type { SeoReadinessResponse } from "../types";

function answer(status: number, data: unknown, error?: unknown) {
  return {
    data: status < 400 ? data : undefined,
    error: status < 400 ? undefined : error,
    response: new Response(null, { status }),
  } as never;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("getSeoReadiness", () => {
  it("returns the readiness payload on success", async () => {
    const readiness: SeoReadinessResponse = { ready: true, batch_pending: false };
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

describe("getListingProposal", () => {
  it("returns the cached proposal", async () => {
    const cached = listingProposal();
    const get = vi.spyOn(api, "GET").mockResolvedValue(answer(200, cached));

    await expect(getListingProposal("take-a-hike")).resolves.toEqual(cached);
    expect(get).toHaveBeenCalledWith("/api/listings/{name}/proposal", {
      params: { path: { name: "take-a-hike" } },
    });
  });

  it("answers null when there is none", async () => {
    vi.spyOn(api, "GET").mockResolvedValue(answer(404, undefined, { detail: "no proposal" }));

    await expect(getListingProposal("take-a-hike")).resolves.toBeNull();
  });

  it("throws SeoApiError on any other failure", async () => {
    vi.spyOn(api, "GET").mockResolvedValue(answer(500, undefined, { detail: "boom" }));

    await expect(getListingProposal("take-a-hike")).rejects.toBeInstanceOf(SeoApiError);
  });
});

describe("resolveListingProposal", () => {
  const patch = { generated_at: "2026-09-23T00:00:00Z", title: "accepted" as const };

  it("sends the sections and returns the updated proposal", async () => {
    const updated = listingProposal({
      resolution: { title: "accepted", tags: "pending", lead: "pending" },
    });
    const send = vi.spyOn(api, "PATCH").mockResolvedValue(answer(200, updated));

    await expect(resolveListingProposal("take-a-hike", patch)).resolves.toEqual(updated);
    expect(send).toHaveBeenCalledWith("/api/listings/{name}/proposal/resolution", {
      params: { path: { name: "take-a-hike" } },
      body: patch,
    });
  });

  it.each([404, 409])("answers null when the proposal is gone or replaced (%i)", async (status) => {
    vi.spyOn(api, "PATCH").mockResolvedValue(answer(status, undefined, { detail: "no" }));

    await expect(resolveListingProposal("take-a-hike", patch)).resolves.toBeNull();
  });

  it("throws SeoApiError on any other failure", async () => {
    vi.spyOn(api, "PATCH").mockResolvedValue(answer(500, undefined, { detail: "boom" }));

    await expect(resolveListingProposal("take-a-hike", patch)).rejects.toBeInstanceOf(SeoApiError);
  });
});
