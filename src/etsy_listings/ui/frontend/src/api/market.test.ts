import { afterEach, expect, it, vi } from "vitest";
import { api } from "./client";
import { MarketApiError, getMarketSnapshot } from "./market";
import { marketSnapshot } from "../test/market";

/** `GET /api/listings/{name}/market`, stubbed at the typed client's `api`
 * seam as `aiRuns.test.ts` does. */

function answer(status: number, data: unknown) {
  return {
    data: status < 400 ? data : undefined,
    error: status < 400 ? undefined : { detail: "no" },
    response: new Response(null, { status }),
  } as never;
}

afterEach(() => {
  vi.restoreAllMocks();
});

it("returns the listing's latest snapshot", async () => {
  const snapshot = marketSnapshot();
  const get = vi.spyOn(api, "GET").mockResolvedValue(answer(200, snapshot));

  await expect(getMarketSnapshot("take-a-hike")).resolves.toEqual(snapshot);
  expect(get).toHaveBeenCalledWith("/api/listings/{name}/market", {
    params: { path: { name: "take-a-hike" } },
  });
});

it("returns null before the first search", async () => {
  vi.spyOn(api, "GET").mockResolvedValue(answer(404, null));

  await expect(getMarketSnapshot("take-a-hike")).resolves.toBeNull();
});

it("throws on any other failure", async () => {
  vi.spyOn(api, "GET").mockResolvedValue(answer(500, null));

  await expect(getMarketSnapshot("take-a-hike")).rejects.toBeInstanceOf(MarketApiError);
});
