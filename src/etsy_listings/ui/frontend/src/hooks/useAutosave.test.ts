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
      variation_images: null,
      renewal: null,
      section: null,
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
  it("starts with listing.yaml's actual modification time", () => {
    const modifiedAt = "2026-09-16T08:30:00Z";
    const { result } = renderHook(() =>
      useAutosave("take-a-hike", detail({ modified_at: modifiedAt })),
    );

    expect(result.current.save).toEqual({
      kind: "saved",
      savedAt: Date.parse(modifiedAt),
    });
  });

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

  it("flush() with nothing pending does not call the server", async () => {
    const spy = vi.spyOn(listingsApi, "patchListing");
    const { result } = renderHook(() => useAutosave("take-a-hike", detail()));

    await act(async () => {
      await result.current.flush();
    });
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

describe("useAutosave before the listing exists", () => {
  const draft = () =>
    detail({ name: "", garment_profile: "", design: {}, colors: [], prices: {}, media: [] });

  it("sends edits to the draft endpoint, never to /api/listings, while unnamed", async () => {
    const describe_ = vi.spyOn(listingsApi, "describeListingDraft").mockResolvedValue(draft());
    const create = vi.spyOn(listingsApi, "createListing");
    const { result, unmount } = renderHook(() => useAutosave(null, draft()));

    act(() => result.current.update({ colors: ["black"] }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    });

    expect(create).not.toHaveBeenCalled();
    // The whole document, not the delta: there is nothing on the server to
    // merge a delta into.
    expect(describe_.mock.calls[0]?.[0]).toMatchObject({ colors: ["black"] });
    expect(result.current.save.kind).toBe("unnamed");
    // An unnamed draft never clears `pending` -- it is what a create will
    // carry -- so unmount here, while the mock is still installed.
    unmount();
  });

  it("naming it creates it, carrying everything edited beforehand", async () => {
    vi.spyOn(listingsApi, "describeListingDraft").mockResolvedValue(draft());
    const create = vi
      .spyOn(listingsApi, "createListing")
      .mockResolvedValue(detail({ name: "my-shirt" }));
    const onNamed = vi.fn();
    const { result } = renderHook(() => useAutosave(null, draft(), { onNamed }));

    act(() => result.current.update({ colors: ["black"] }));
    await act(async () => {
      result.current.commitName("my-shirt");
      await Promise.resolve();
    });

    expect(create).toHaveBeenCalledTimes(1);
    expect(create.mock.calls[0]?.[0].name).toBe("my-shirt");
    expect(create.mock.calls[0]?.[0].document).toMatchObject({ colors: ["black"] });
    expect(onNamed).toHaveBeenCalledWith("my-shirt", expect.objectContaining({ name: "my-shirt" }));
    expect(result.current.save.kind).toBe("saved");
  });

  it("a document the server will not write leaves it unsaved, and retries on the next edit", async () => {
    vi.spyOn(listingsApi, "describeListingDraft").mockResolvedValue(draft());
    const create = vi
      .spyOn(listingsApi, "createListing")
      // An empty `name` is the "not created" signal (see `createListing`).
      .mockResolvedValueOnce(draft())
      .mockResolvedValueOnce(detail({ name: "my-shirt" }));
    const onNamed = vi.fn();
    const { result } = renderHook(() => useAutosave(null, draft(), { onNamed }));

    await act(async () => {
      result.current.commitName("my-shirt");
      await Promise.resolve();
    });
    expect(result.current.save.kind).toBe("unsaved");
    expect(onNamed).not.toHaveBeenCalled();

    // The edit that supplies what was missing is the retry -- the user does
    // not have to type the name again.
    act(() => result.current.update({ pricing_plan: "../../pricing-plans/tee.yaml" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    });

    expect(create).toHaveBeenCalledTimes(2);
    expect(create.mock.calls[1]?.[0].document).toMatchObject({
      pricing_plan: "../../pricing-plans/tee.yaml",
    });
    expect(onNamed).toHaveBeenCalledWith("my-shirt", expect.objectContaining({ name: "my-shirt" }));
  });

  it("a taken name is reported without losing the draft", async () => {
    vi.spyOn(listingsApi, "describeListingDraft").mockResolvedValue(draft());
    vi.spyOn(listingsApi, "createListing").mockRejectedValue(
      new listingsApi.ListingsApiError("409"),
    );
    const { result, unmount } = renderHook(() => useAutosave(null, draft()));

    act(() => result.current.update({ colors: ["black"] }));
    await act(async () => {
      result.current.commitName("take-a-hike");
      await Promise.resolve();
    });

    expect(result.current.save).toEqual({ kind: "name-taken", name: "take-a-hike" });
    expect(result.current.detail.colors).toEqual(["black"]);
    unmount();
  });

  it("normalises a bare design ref locally the way the server stores it", () => {
    vi.spyOn(listingsApi, "describeListingDraft").mockResolvedValue(draft());
    const { result, unmount } = renderHook(() => useAutosave(null, draft()));

    // What `DesignSelect` sends. Held as a string, `Object.keys` on it reports
    // one "artwork" per character.
    act(() => result.current.update({ design: "../../designs/take-a-hike.png" }));

    expect(result.current.detail.design).toEqual({ default: "../../designs/take-a-hike.png" });
    unmount();
  });
});

describe("useAutosave renaming", () => {
  it("drains pending edits under the old name before the directory moves", async () => {
    const order: string[] = [];
    vi.spyOn(listingsApi, "patchListing").mockImplementation(async () => {
      order.push("patch");
      return detail();
    });
    vi.spyOn(listingsApi, "renameListing").mockImplementation(async () => {
      order.push("rename");
      return detail({ name: "hike-away" });
    });
    const onNamed = vi.fn();
    const { result } = renderHook(() => useAutosave("take-a-hike", detail(), { onNamed }));

    act(() => result.current.update({ colors: ["white"] }));
    await act(async () => {
      result.current.commitName("hike-away");
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(order).toEqual(["patch", "rename"]);
    expect(onNamed).toHaveBeenCalledWith(
      "hike-away",
      expect.objectContaining({ name: "hike-away" }),
    );
  });

  it("a rename the server refuses leaves the listing where it was", async () => {
    vi.spyOn(listingsApi, "renameListing").mockRejectedValue(
      new listingsApi.ListingsApiError("409"),
    );
    const onNamed = vi.fn();
    const { result } = renderHook(() => useAutosave("take-a-hike", detail(), { onNamed }));

    await act(async () => {
      result.current.commitName("taken");
      await Promise.resolve();
    });

    expect(result.current.save).toEqual({ kind: "name-taken", name: "taken" });
    expect(onNamed).not.toHaveBeenCalled();
  });

  it("committing the name it already has does nothing", async () => {
    const rename = vi.spyOn(listingsApi, "renameListing");
    const { result } = renderHook(() => useAutosave("take-a-hike", detail()));

    await act(async () => {
      result.current.commitName("take-a-hike");
      await Promise.resolve();
    });

    expect(rename).not.toHaveBeenCalled();
  });
});
