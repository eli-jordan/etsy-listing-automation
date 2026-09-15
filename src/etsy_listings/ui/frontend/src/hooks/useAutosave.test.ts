import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as listingsApi from "../api/listings";
import type { ListingDetail } from "../types";
import { AUTOSAVE_DEBOUNCE_MS, useAutosave } from "./useAutosave";

function detail(over: Partial<ListingDetail> = {}): ListingDetail {
  return {
    garment_profile: "comfort-colors-1717",
    design: { default: "../../designs/take-a-hike.png" },
    colors: ["black"],
    brief: "",
    prices: {},
    price_overrides: {},
    artwork: {},
    pricing_plan: null,
    etsy: {
      title: "<generate>",
      description: "<generate>",
      tags: "<generate>",
      materials: [],
      variation_images: null,
      renewal: null,
      section: null,
      shipping_profile: null,
    },
    media: [],
    name: "take-a-hike",
    status: "draft",
    issues: [],
    field_errors: {},
    etsy_listing_id: null,
    printify_product_id: null,
    pricing_plan_name: null,
    resolved_prices: [],
    ...over,
  };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("useAutosave", () => {
  it("applies a patch to local state immediately, before the network round-trip", () => {
    vi.spyOn(listingsApi, "patchListing").mockResolvedValue(detail());
    const { result, unmount } = renderHook(() => useAutosave("take-a-hike", detail()));

    act(() => result.current.update({ colors: ["black", "white"] }));

    expect(result.current.detail.colors).toEqual(["black", "white"]);
    // The debounce never fired (fake timers, never advanced) -- flush the
    // still-pending PATCH here, while the mock above is still installed,
    // rather than leaving it for the global auto-unmount to hit a real fetch.
    unmount();
  });

  it("sends the patch to the server only after the debounce elapses", async () => {
    const spy = vi.spyOn(listingsApi, "patchListing").mockResolvedValue(detail());
    const { result } = renderHook(() => useAutosave("take-a-hike", detail()));

    act(() => result.current.update({ colors: ["white"] }));
    expect(spy).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    });
    expect(spy).toHaveBeenCalledWith("take-a-hike", { colors: ["white"] });
  });

  it("merges several edits made before the debounce fires into one PATCH", async () => {
    const spy = vi.spyOn(listingsApi, "patchListing").mockResolvedValue(detail());
    const { result } = renderHook(() => useAutosave("take-a-hike", detail()));

    act(() => result.current.update({ colors: ["white"] }));
    act(() => result.current.update({ garment_profile: "gildan-5000" }));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    });
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith("take-a-hike", {
      colors: ["white"],
      garment_profile: "gildan-5000",
    });
  });

  it("merges edits to different etsy sub-fields into one nested object", async () => {
    const spy = vi.spyOn(listingsApi, "patchListing").mockResolvedValue(detail());
    const { result } = renderHook(() => useAutosave("take-a-hike", detail()));

    act(() => result.current.update({ etsy: { title: "New Title" } }));
    act(() => result.current.update({ etsy: { section: "Apparel" } }));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    });
    expect(spy).toHaveBeenCalledWith("take-a-hike", {
      etsy: { title: "New Title", section: "Apparel" },
    });
  });

  it("replaces local state with the server's response once it lands", async () => {
    const server = detail({ colors: ["white"], issues: [] });
    vi.spyOn(listingsApi, "patchListing").mockResolvedValue(server);
    const { result } = renderHook(() => useAutosave("take-a-hike", detail()));

    act(() => result.current.update({ colors: ["white"] }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    });

    expect(result.current.detail).toBe(server);
  });

  it("flush() sends immediately without waiting for the debounce", async () => {
    const spy = vi.spyOn(listingsApi, "patchListing").mockResolvedValue(detail());
    const { result } = renderHook(() => useAutosave("take-a-hike", detail()));

    act(() => result.current.update({ colors: ["white"] }));
    await act(async () => {
      result.current.flush();
      await Promise.resolve();
    });

    expect(spy).toHaveBeenCalledWith("take-a-hike", { colors: ["white"] });
  });

  it("flush() with nothing pending does not call the server", () => {
    const spy = vi.spyOn(listingsApi, "patchListing");
    const { result } = renderHook(() => useAutosave("take-a-hike", detail()));

    act(() => result.current.flush());
    expect(spy).not.toHaveBeenCalled();
  });

  it("flushes a pending edit on unmount so it is never silently lost", async () => {
    const spy = vi.spyOn(listingsApi, "patchListing").mockResolvedValue(detail());
    const { result, unmount } = renderHook(() => useAutosave("take-a-hike", detail()));

    act(() => result.current.update({ colors: ["white"] }));
    unmount();

    expect(spy).toHaveBeenCalledWith("take-a-hike", { colors: ["white"] });
  });
});
