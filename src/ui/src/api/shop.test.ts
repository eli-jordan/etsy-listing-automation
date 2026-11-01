import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { getShop, getShopConnections, getShopLookups, saveShop, ShopApiError } from "./shop";

function answer(status: number, data?: unknown, error?: unknown) {
  return { data, error, response: new Response(null, { status }) } as never;
}

afterEach(() => vi.restoreAllMocks());

describe("shop api", () => {
  it("reads the shop and fails loudly with the server's sentence", async () => {
    vi.spyOn(api, "GET").mockResolvedValueOnce(answer(200, { revision: "r1" }));
    await expect(getShop()).resolves.toEqual({ revision: "r1" });

    vi.spyOn(api, "GET").mockResolvedValueOnce(
      answer(422, undefined, { detail: "shop.yaml: unknown key" }),
    );
    await expect(getShop()).rejects.toThrow("shop.yaml: unknown key");
  });

  it("sends the revision with only the changed keys", async () => {
    const patch = vi.spyOn(api, "PATCH").mockResolvedValue(answer(200, { revision: "r2" }));

    await expect(saveShop("r1", { renewal: "auto" })).resolves.toEqual({
      kind: "saved",
      shop: { revision: "r2" },
    });
    expect(patch.mock.calls[0]?.[1]).toEqual({
      body: { revision: "r1", changes: { renewal: "auto" } },
    });
  });

  it("tells a conflict, field errors and a failure apart", async () => {
    vi.spyOn(api, "PATCH").mockResolvedValueOnce(
      answer(409, undefined, { kind: "conflict", message: "changed", field_errors: {} }),
    );
    await expect(saveShop("r1", {})).resolves.toEqual({ kind: "conflict", message: "changed" });

    vi.spyOn(api, "PATCH").mockResolvedValueOnce(
      answer(422, undefined, {
        kind: "invalid",
        message: "bad",
        field_errors: { "etsy.listing_defaults.renewal": "nope" },
      }),
    );
    await expect(saveShop("r1", {})).resolves.toEqual({
      kind: "invalid",
      message: "bad",
      fieldErrors: { renewal: "nope" },
    });

    vi.spyOn(api, "PATCH").mockResolvedValueOnce(answer(500, undefined, {}));
    await expect(saveShop("r1", {})).rejects.toBeInstanceOf(ShopApiError);
  });

  it("reads connections and lookups", async () => {
    vi.spyOn(api, "GET").mockResolvedValueOnce(answer(200, { etsy: {}, printify: {} }));
    await expect(getShopConnections()).resolves.toEqual({ etsy: {}, printify: {} });
    vi.spyOn(api, "GET").mockResolvedValueOnce(answer(500, undefined, {}));
    await expect(getShopLookups()).rejects.toBeInstanceOf(ShopApiError);
  });
});
