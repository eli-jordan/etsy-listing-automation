import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { createEtsySection, listCommonCopy, listEtsySections, tryGetListing } from "./listings";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("createEtsySection", () => {
  it("creates a shop section and returns Etsy's saved row", async () => {
    const section = { id: 44, title: "Trail Gear" };
    const post = vi.spyOn(api, "POST").mockResolvedValue({
      data: section,
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    await expect(createEtsySection("Trail Gear")).resolves.toEqual(section);
    expect(post).toHaveBeenCalledWith("/api/etsy/sections", {
      body: { title: "Trail Gear" },
    });
  });
});

describe("listEtsySections", () => {
  it("preserves an available shop's empty section list", async () => {
    const result = { available: true, sections: [] };
    vi.spyOn(api, "GET").mockResolvedValue({
      data: result,
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    await expect(listEtsySections()).resolves.toEqual(result);
  });
});

describe("tryGetListing", () => {
  it("is null, not an error, for a listing that no longer exists", async () => {
    vi.spyOn(api, "GET").mockResolvedValue({
      data: undefined,
      error: { detail: "no listing" },
      response: new Response(null, { status: 404 }),
    } as never);

    await expect(tryGetListing("gone")).resolves.toBeNull();
  });
});

describe("listCommonCopy", () => {
  it("is empty, not an error, when the read fails", async () => {
    vi.spyOn(api, "GET").mockResolvedValue({
      data: undefined,
      error: { detail: "boom" },
      response: new Response(null, { status: 500 }),
    } as never);

    await expect(listCommonCopy()).resolves.toEqual([]);
  });

  it("is empty, not an error, when the server cannot be reached", async () => {
    vi.spyOn(api, "GET").mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(listCommonCopy()).resolves.toEqual([]);
  });
});
