import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as listingsApi from "../api/listings";
import { listingDetail as detail } from "../test/listings";
import type { ListingDetail } from "../types";
import type { AutosaveTransport } from "./listingAutosave";
import { LISTING_TRANSPORT, useAutosave } from "./useAutosave";
import { AUTOSAVE_DEBOUNCE_MS } from "./writeLoop";

/** The React binding and the listing's transport. What the editor does with an
 * edit is `listingAutosave.test.ts`'s, and how writes are ordered `writeLoop.test.ts`'s. */

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("useAutosave", () => {
  it("renders an edit at once, and the response once it lands", async () => {
    const server = detail({ colors: ["white"], issues: [] });
    vi.spyOn(listingsApi, "patchListing").mockResolvedValue(server);
    const { result } = renderHook(() => useAutosave("take-a-hike", detail()));

    act(() => result.current.update({ colors: ["white"] }));
    expect(result.current.detail.colors).toEqual(["white"]);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    });
    expect(result.current.detail).toBe(server);
    expect(result.current.save.kind).toBe("saved");
  });

  it("flushes a pending edit on unmount, in the same turn", () => {
    const spy = vi.spyOn(listingsApi, "patchListing").mockResolvedValue(detail());
    const { result, unmount } = renderHook(() => useAutosave("take-a-hike", detail()));

    act(() => result.current.update({ colors: ["white"] }));
    unmount();

    expect(spy).toHaveBeenCalledWith("take-a-hike", { colors: ["white"] });
  });

  it("still sends an edit made after it unmounted", async () => {
    const spy = vi.spyOn(listingsApi, "patchListing").mockResolvedValue(detail());
    const { result, unmount } = renderHook(() => useAutosave("take-a-hike", detail()));
    const { update, flush } = result.current;

    unmount();
    update({ colors: ["white"] });
    await flush();

    expect(spy).toHaveBeenCalledWith("take-a-hike", { colors: ["white"] });
  });

  it("does not retry a refused edit when onNamed changes on every render", async () => {
    const patch = vi
      .spyOn(listingsApi, "patchListing")
      .mockResolvedValue(detail({ field_errors: { __root__: "no" } }));
    const { result } = renderHook(() =>
      useAutosave("take-a-hike", detail(), { onNamed: () => undefined }),
    );

    act(() => result.current.update({ colors: ["white"] }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS * 3);
    });

    expect(patch).toHaveBeenCalledTimes(1);
  });

  it("names through the latest onNamed", async () => {
    vi.spyOn(listingsApi, "renameListing").mockResolvedValue(detail({ name: "hike-away" }));
    const first = vi.fn();
    const latest = vi.fn();
    const { result, rerender } = renderHook(
      ({ onNamed }) => useAutosave("take-a-hike", detail(), { onNamed }),
      { initialProps: { onNamed: first } },
    );

    rerender({ onNamed: latest });
    await act(async () => {
      result.current.commitName("hike-away");
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(first).not.toHaveBeenCalled();
    expect(latest).toHaveBeenCalledTimes(1);
  });

  it("uses the transport it mounted with", async () => {
    const save = vi.fn<AutosaveTransport["save"]>(async () => ({
      saved: true,
      detail: detail(),
    }));
    const transport = { ...LISTING_TRANSPORT, save };
    const { result } = renderHook(() => useAutosave("heavyweight-tee", detail(), { transport }));

    act(() => result.current.update({ colors: ["white"] }));
    await act(async () => {
      await result.current.flush();
    });

    expect(save).toHaveBeenCalledTimes(1);
  });
});

describe("LISTING_TRANSPORT", () => {
  const refusing = (): ListingDetail => detail({ field_errors: { __root__: "no" } });

  it("sends a PATCH of the delta alone", async () => {
    const patch = vi.spyOn(listingsApi, "patchListing").mockResolvedValue(detail());

    await LISTING_TRANSPORT.save("take-a-hike", { colors: ["white"] }, { colors: ["white"] });

    expect(patch).toHaveBeenCalledWith("take-a-hike", { colors: ["white"] });
  });

  it("calls a 200 with field errors not saved", async () => {
    vi.spyOn(listingsApi, "patchListing").mockResolvedValue(refusing());

    await expect(LISTING_TRANSPORT.save("take-a-hike", {}, {})).resolves.toEqual({
      saved: false,
      issues: null,
      field_errors: { __root__: "no" },
    });
  });

  it("calls a create that answers no name not saved, keeping only the errors", async () => {
    vi.spyOn(listingsApi, "createListing").mockResolvedValue({ ...refusing(), name: "" });

    await expect(LISTING_TRANSPORT.create("my-shirt", {})).resolves.toEqual({
      saved: false,
      issues: null,
      field_errors: { __root__: "no" },
    });
  });

  it("creates with the name and the whole document", async () => {
    const created = detail({ name: "my-shirt" });
    const create = vi.spyOn(listingsApi, "createListing").mockResolvedValue(created);

    await expect(LISTING_TRANSPORT.create("my-shirt", { colors: ["black"] })).resolves.toEqual({
      saved: true,
      detail: created,
    });
    expect(create).toHaveBeenCalledWith({ name: "my-shirt", document: { colors: ["black"] } });
  });
});
