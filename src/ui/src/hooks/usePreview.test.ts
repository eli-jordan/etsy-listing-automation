import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../api/calibrator";
import { type Deferred, deferred, must } from "../test/helpers";
import { PREVIEW_DEBOUNCE_MS, usePreview } from "./usePreview";

/** Non-nullable, because one test spreads it: the hook's parameter includes
 * `null` (meaning "hold off"), and spreading that widens the whole thing to
 * `{}`. */
type Body = NonNullable<Parameters<typeof usePreview>[1]>;

const BODY: Body = {
  bounding_box: [
    { x: 0, y: 0 },
    { x: 100, y: 0 },
    { x: 100, y: 100 },
    { x: 0, y: 100 },
  ],
  displace: { enabled: false, strength: 0 },
  shade: { enabled: true, opacity: 0.6, blend: "soft-light" },
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.mocked(URL.revokeObjectURL).mockClear();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

/** Every render request, each held open until the test settles it. The clock
 * and the network are separate controls: advancing time sends a request,
 * settling its deferred delivers the response. */
function heldRenders() {
  const pending: Deferred<string>[] = [];
  const spy = vi.spyOn(calibrator, "renderPreview").mockImplementation(() => {
    const next = deferred<string>();
    pending.push(next);
    return next.promise;
  });
  const settle = async (index: number, url: string) => {
    await act(async () => must(pending[index]).resolve(url));
  };
  const fail = async (index: number) => {
    await act(async () => must(pending[index]).reject(new Error("preview failed")));
  };
  return { spy, settle, fail };
}

async function debounce(ms = PREVIEW_DEBOUNCE_MS) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("usePreview", () => {
  it("asks for a preview once the debounce has elapsed, and shows what comes back", async () => {
    const { spy, settle } = heldRenders();
    const { result } = renderHook(() => usePreview("lifestyle-01", BODY, "bundled-grid"));

    await debounce(PREVIEW_DEBOUNCE_MS - 1);
    expect(spy).not.toHaveBeenCalled();
    await debounce(1);
    expect(spy).toHaveBeenCalledWith("lifestyle-01", BODY, "bundled-grid", "editor");
    expect(result.current).toBeNull();

    await settle(0, "blob:one");
    expect(result.current).toBe("blob:one");
  });

  it("sends one request for edits made within the debounce, carrying the last", async () => {
    const { spy } = heldRenders();
    const { rerender } = renderHook(({ design }) => usePreview("lifestyle-01", BODY, design), {
      initialProps: { design: "d0" },
    });

    for (const design of ["d1", "d2", "d3"]) {
      await debounce(PREVIEW_DEBOUNCE_MS / 2);
      rerender({ design });
    }
    await debounce();
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith("lifestyle-01", BODY, "d3", "editor");
  });

  it("revokes the displayed object URL when the editor unmounts", async () => {
    const { settle } = heldRenders();
    const { result, unmount } = renderHook(() => usePreview("lifestyle-01", BODY, "bundled-grid"));
    await debounce();
    await settle(0, "blob:one");
    expect(result.current).toBe("blob:one");

    // The leak this hook was extracted to fix: each editor's own cleanup
    // cleared the debounce timer but left the blob it was displaying alive, so
    // every template switch stranded one in the document.
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:one");
  });

  it("revokes the previous URL when a new preview replaces it", async () => {
    const { settle } = heldRenders();
    const { result, rerender } = renderHook(
      ({ design }) => usePreview("lifestyle-01", BODY, design),
      { initialProps: { design: "bundled-grid" } },
    );
    await debounce();
    await settle(0, "blob:one");

    rerender({ design: "bundled-on-dark" });
    await debounce();
    await settle(1, "blob:two");
    expect(result.current).toBe("blob:two");
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:one");
  });

  it("asks for nothing while the body is null", async () => {
    const { spy } = heldRenders();
    const { result } = renderHook(() => usePreview("flat-lay-01", null, "bundled-grid"));

    await debounce();
    expect(vi.getTimerCount()).toBe(0);
    expect(spy).not.toHaveBeenCalled();
    expect(result.current).toBeNull();
  });

  it("does not re-request when the body is rebuilt with equal values", async () => {
    const { spy, settle } = heldRenders();
    const { rerender } = renderHook(() =>
      // A fresh object literal every render, as an editor produces.
      usePreview("lifestyle-01", { ...BODY }, "bundled-grid"),
    );
    await debounce();
    await settle(0, "blob:one");

    rerender();
    rerender();
    await debounce();
    expect(vi.getTimerCount()).toBe(0);
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("keeps the last good preview on screen when a render fails", async () => {
    const { spy, settle, fail } = heldRenders();
    const { result, rerender } = renderHook(
      ({ design }) => usePreview("lifestyle-01", BODY, design),
      { initialProps: { design: "bundled-grid" } },
    );
    await debounce();
    await settle(0, "blob:one");

    rerender({ design: "bundled-on-dark" });
    await debounce();
    expect(spy).toHaveBeenCalledTimes(2);
    await fail(1);
    expect(result.current).toBe("blob:one");
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
  });
});

describe("usePreview's one-at-a-time rule", () => {
  it("coalesces edits made during a render into a single follow-up", async () => {
    const { spy, settle } = heldRenders();
    const { result, rerender } = renderHook(
      ({ design }) => usePreview("flat-lay-01", BODY, design),
      { initialProps: { design: "d0" } },
    );
    await debounce();
    expect(spy).toHaveBeenCalledTimes(1);

    // Three edits while the first render is still out, each past its own
    // debounce. None of them may be sent -- queueing them would make every
    // frame arrive later than the last.
    for (const design of ["d1", "d2", "d3"]) {
      rerender({ design });
      await debounce();
    }
    expect(spy).toHaveBeenCalledTimes(1);

    await settle(0, "blob:first");
    expect(spy).toHaveBeenCalledTimes(2);
    // The newest, not the oldest of the three.
    expect(spy).toHaveBeenLastCalledWith("flat-lay-01", BODY, "d3", "editor");
    // The first response is still the newest frame there is, so it shows
    // while the follow-up renders.
    expect(result.current).toBe("blob:first");

    await settle(1, "blob:final");
    expect(result.current).toBe("blob:final");
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("drops a render that lands after the editor has moved to another template", async () => {
    const { spy, settle } = heldRenders();
    const { result, rerender } = renderHook(({ name }) => usePreview(name, BODY, "bundled-grid"), {
      initialProps: { name: "flat-lay-01" },
    });
    await debounce();

    rerender({ name: "lifestyle-01" });
    await settle(0, "blob:stale");
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:stale");
    expect(result.current).toBeNull();

    await debounce();
    expect(spy).toHaveBeenLastCalledWith("lifestyle-01", BODY, "bundled-grid", "editor");
    await settle(1, "blob:other");
    expect(result.current).toBe("blob:other");
  });
});
