import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PRELOAD_CONCURRENCY, usePreloadedPictures } from "./usePreloadedPictures";

/** A fetch whose responses the test settles by hand, recording what was
 * asked for and how many were in flight at once. */
function controlledFetch() {
  const requested: string[] = [];
  const pending = new Map<string, () => void>();
  let inFlight = 0;
  let peak = 0;
  const fetch = vi.fn((url: string, init?: RequestInit) => {
    requested.push(url);
    inFlight += 1;
    peak = Math.max(peak, inFlight);
    return new Promise<Response>((resolve, reject) => {
      init?.signal?.addEventListener("abort", () => {
        inFlight -= 1;
        reject(new DOMException("aborted", "AbortError"));
      });
      pending.set(url, () => {
        inFlight -= 1;
        resolve(new Response("png"));
      });
    });
  });
  vi.stubGlobal("fetch", fetch);
  return {
    requested,
    peak: () => peak,
    settle: (url: string) => pending.get(url)?.(),
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("usePreloadedPictures", () => {
  it("fetches every picture in list order, a few at a time", async () => {
    const net = controlledFetch();
    const urls = ["/a", "/b", "/c", "/d"];
    renderHook(() => usePreloadedPictures(urls));

    await waitFor(() => expect(net.requested).toEqual(["/a", "/b"]));
    net.settle("/a");
    await waitFor(() => expect(net.requested).toEqual(["/a", "/b", "/c"]));
    net.settle("/b");
    net.settle("/c");
    await waitFor(() => expect(net.requested).toEqual(urls));
    expect(net.peak()).toBe(PRELOAD_CONCURRENCY);
  });

  it("does not start again when the same pictures are asked for in a new array", async () => {
    const net = controlledFetch();
    const { rerender } = renderHook(({ urls }) => usePreloadedPictures(urls), {
      initialProps: { urls: ["/a"] },
    });
    await waitFor(() => expect(net.requested).toEqual(["/a"]));

    rerender({ urls: ["/a"] });

    expect(net.requested).toEqual(["/a"]);
  });

  it("abandons the old pictures when the list changes", async () => {
    const net = controlledFetch();
    const { rerender } = renderHook(({ urls }) => usePreloadedPictures(urls), {
      initialProps: { urls: ["/old-1", "/old-2", "/old-3"] },
    });
    await waitFor(() => expect(net.requested).toHaveLength(2));

    rerender({ urls: ["/new"] });
    net.settle("/old-1");

    await waitFor(() => expect(net.requested).toContain("/new"));
    expect(net.requested).not.toContain("/old-3");
  });

  it("carries on past a picture that fails", async () => {
    const fetch = vi.fn((url: string) =>
      url === "/broken" ? Promise.reject(new Error("500")) : Promise.resolve(new Response("png")),
    );
    vi.stubGlobal("fetch", fetch);
    renderHook(() => usePreloadedPictures(["/broken", "/x", "/y"]));

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
  });
});
