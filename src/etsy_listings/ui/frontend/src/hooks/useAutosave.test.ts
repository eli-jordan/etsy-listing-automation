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
      title: "",
      description: { lead: "", text: null, ref: null },
      tags: [],
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
    description_composed: "",
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

  it("keeps newer brief text visible when an older save response arrives", async () => {
    let finishFirst!: (value: ListingDetail) => void;
    const first = new Promise<ListingDetail>((resolve) => {
      finishFirst = resolve;
    });
    vi.spyOn(listingsApi, "patchListing")
      .mockReturnValueOnce(first)
      .mockResolvedValue(detail({ brief: "A trail shirt." }));
    const { result, unmount } = renderHook(() => useAutosave("take-a-hike", detail()));

    act(() => result.current.update({ brief: "A trail" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    });
    act(() => result.current.update({ brief: "A trail shirt." }));
    expect(result.current.detail.brief).toBe("A trail shirt.");

    await act(async () => finishFirst(detail({ brief: "A trail" })));
    expect(result.current.detail.brief).toBe("A trail shirt.");
    unmount();
  });

  it("serializes edits made while an earlier save is in flight", async () => {
    let finishFirst!: (value: ListingDetail) => void;
    const first = new Promise<ListingDetail>((resolve) => {
      finishFirst = resolve;
    });
    const patch = vi
      .spyOn(listingsApi, "patchListing")
      .mockReturnValueOnce(first)
      .mockResolvedValue(detail({ brief: "A trail shirt." }));
    const { result } = renderHook(() => useAutosave("take-a-hike", detail()));

    act(() => result.current.update({ brief: "A trail" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    });
    act(() => result.current.update({ brief: "A trail shirt." }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    });
    expect(patch).toHaveBeenCalledTimes(1);
    expect(result.current.detail.brief).toBe("A trail shirt.");

    await act(async () => finishFirst(detail({ brief: "A trail" })));
    expect(patch).toHaveBeenCalledTimes(2);
    expect(patch).toHaveBeenLastCalledWith("take-a-hike", { brief: "A trail shirt." });
    expect(result.current.detail.brief).toBe("A trail shirt.");
    expect(result.current.save.kind).toBe("saved");
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

  it("a PATCH the server rejects leaves the edit pending, retried by the next flush", async () => {
    /* A named listing's autosave has no retry loop of its own -- the next
       edit (or the next debounce) is what tries again. What must not happen
       is silently losing the patch: `flush()`'s old behaviour cleared
       `pending` before the request settled, so a rejected PATCH dropped the
       edit on the floor (worse now that a source switch in the Description
       editor can carry a whole `lead`/`text`/`ref` triple, not just one
       field -- AI SEO implementation plan, PR6). */
    const patch = vi
      .spyOn(listingsApi, "patchListing")
      .mockRejectedValueOnce(new listingsApi.ListingsApiError("500"))
      .mockResolvedValueOnce(detail({ etsy: { ...detail().etsy, title: "Take A Hike Tee" } }));
    const { result } = renderHook(() => useAutosave("take-a-hike", detail()));

    act(() => result.current.update({ etsy: { title: "Take A Hike Tee" } }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    });

    expect(result.current.save).toEqual({ kind: "save-failed" });
    // The edit itself is not lost, either in local state or in what the
    // next flush will send.
    expect(result.current.detail.etsy.title).toBe("Take A Hike Tee");

    await act(async () => {
      await result.current.flush();
    });

    expect(patch).toHaveBeenCalledTimes(2);
    expect(patch).toHaveBeenLastCalledWith("take-a-hike", { etsy: { title: "Take A Hike Tee" } });
    expect(result.current.save.kind).toBe("saved");
  });

  it("never sends a second PATCH while one is still in flight", async () => {
    let resolveFirst!: (value: ListingDetail) => void;
    const firstPromise = new Promise<ListingDetail>((resolve) => {
      resolveFirst = resolve;
    });
    const patch = vi
      .spyOn(listingsApi, "patchListing")
      .mockImplementationOnce(() => firstPromise)
      .mockResolvedValueOnce(detail({ etsy: { ...detail().etsy, section: "Apparel" } }));
    const { result } = renderHook(() => useAutosave("take-a-hike", detail()));

    act(() => result.current.update({ etsy: { title: "Take A Hike Tee" } }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    });
    expect(patch).toHaveBeenCalledTimes(1);
    expect(result.current.save.kind).toBe("saving");

    // A second edit arrives, and its debounce fires, while the first PATCH
    // is still unresolved.
    act(() => result.current.update({ etsy: { section: "Apparel" } }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    });
    // Deferred, not sent concurrently.
    expect(patch).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveFirst(detail());
      await vi.advanceTimersByTimeAsync(0);
    });

    // Once the first PATCH lands, the deferred flush picks up whatever is
    // pending now and sends it -- one request at a time.
    expect(patch).toHaveBeenCalledTimes(2);
    expect(patch).toHaveBeenLastCalledWith("take-a-hike", { etsy: { section: "Apparel" } });
    expect(result.current.save.kind).toBe("saved");
  });

  it("a deferred flush merges with whatever else arrived once an in-flight failure restores it", async () => {
    let rejectFirst!: (err: unknown) => void;
    const firstPromise = new Promise<ListingDetail>((_, reject) => {
      rejectFirst = reject;
    });
    const patch = vi
      .spyOn(listingsApi, "patchListing")
      .mockImplementationOnce(() => firstPromise)
      .mockResolvedValueOnce(detail());
    const { result } = renderHook(() => useAutosave("take-a-hike", detail()));

    act(() => result.current.update({ etsy: { title: "Take A Hike Tee" } }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    });

    act(() => result.current.update({ etsy: { section: "Apparel" } }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    });
    expect(patch).toHaveBeenCalledTimes(1);

    await act(async () => {
      rejectFirst(new listingsApi.ListingsApiError("500"));
      await vi.advanceTimersByTimeAsync(0);
    });

    // The failed patch's restored edit and the edit that arrived while it
    // was in flight are merged into the deferred retry -- neither is lost,
    // and `save` reflects the final outcome, not a stale one.
    expect(patch).toHaveBeenCalledTimes(2);
    expect(patch).toHaveBeenLastCalledWith("take-a-hike", {
      etsy: { title: "Take A Hike Tee", section: "Apparel" },
    });
    expect(result.current.save.kind).toBe("saved");
  });

  it("a later edit after a failed save is merged with the still-pending one", async () => {
    const patch = vi
      .spyOn(listingsApi, "patchListing")
      .mockRejectedValueOnce(new listingsApi.ListingsApiError("500"))
      .mockResolvedValueOnce(detail());
    const { result } = renderHook(() => useAutosave("take-a-hike", detail()));

    act(() => result.current.update({ etsy: { title: "Take A Hike Tee" } }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    });
    expect(result.current.save).toEqual({ kind: "save-failed" });

    act(() => result.current.update({ etsy: { section: "Apparel" } }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    });

    expect(patch).toHaveBeenLastCalledWith("take-a-hike", {
      etsy: { title: "Take A Hike Tee", section: "Apparel" },
    });
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

  it("keeps an edit made while the create was in flight", async () => {
    /* The window PRD 68's drafted brief resolves in: a design pick names the
       draft and starts the create, and the brief arrives before the server
       answers. Clearing `pending` wholesale on success dropped it every time,
       silently -- the listing appeared, the brief did not, and nothing said
       so. `applyResponse` already stated this rule for a PATCH. */
    vi.spyOn(listingsApi, "describeListingDraft").mockResolvedValue(draft());
    let finish: ((fresh: ListingDetail) => void) | undefined;
    vi.spyOn(listingsApi, "createListing").mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const patch = vi
      .spyOn(listingsApi, "patchListing")
      .mockResolvedValue(detail({ name: "my-shirt" }));
    const { result } = renderHook(() => useAutosave(null, draft(), {}));

    act(() => result.current.update({ colors: ["black"] }));
    act(() => result.current.commitName("my-shirt"));
    // Lands after the request went out, before it comes back.
    act(() => result.current.update({ brief: "Drafted from the design." }));
    await act(async () => {
      finish?.(detail({ name: "my-shirt" }));
      await Promise.resolve();
    });
    await act(async () => {
      await result.current.flush();
    });

    // The follow-up carries the edits the create already wrote as well: an
    // edit merges onto whatever is pending, so keeping the later object keeps
    // both. Re-sending a value the file already has costs one PATCH and
    // changes nothing, which is the cheaper of the two mistakes available
    // here.
    expect(patch).toHaveBeenCalledWith(
      "my-shirt",
      expect.objectContaining({ brief: "Drafted from the design." }),
    );
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
