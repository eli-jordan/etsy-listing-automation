import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { getSeoReadiness, SeoApiError } from "./seo";
import type { SeoReadinessResponse } from "../types";

afterEach(() => {
  vi.restoreAllMocks();
});

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
