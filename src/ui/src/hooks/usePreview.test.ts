import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../api/calibrator";
import { usePreview } from "./usePreview";

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
  vi.mocked(URL.revokeObjectURL).mockClear();
});

afterEach(() => vi.restoreAllMocks());

describe("usePreview", () => {
  it("fetches a preview and returns its object URL", async () => {
    const spy = vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:one");
    const { result } = renderHook(() => usePreview("lifestyle-01", BODY, "bundled-grid"));

    await waitFor(() => expect(result.current).toBe("blob:one"));
    expect(spy).toHaveBeenCalledWith("lifestyle-01", BODY, "bundled-grid", "editor");
  });

  it("revokes the displayed object URL when the editor unmounts", async () => {
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:one");
    const { result, unmount } = renderHook(() => usePreview("lifestyle-01", BODY, "bundled-grid"));
    await waitFor(() => expect(result.current).toBe("blob:one"));

    // The leak this hook was extracted to fix: each editor's own cleanup
    // cleared the debounce timer but left the blob it was displaying alive, so
    // every template switch stranded one in the document.
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:one");
  });

  it("revokes the previous URL when a new preview replaces it", async () => {
    vi.spyOn(calibrator, "renderPreview")
      .mockResolvedValueOnce("blob:one")
      .mockResolvedValueOnce("blob:two");
    const { result, rerender } = renderHook(
      ({ design }) => usePreview("lifestyle-01", BODY, design),
      { initialProps: { design: "bundled-grid" } },
    );
    await waitFor(() => expect(result.current).toBe("blob:one"));

    rerender({ design: "bundled-on-dark" });
    await waitFor(() => expect(result.current).toBe("blob:two"));
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:one");
  });

  it("asks for nothing while the body is null", async () => {
    const spy = vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:one");
    const { result } = renderHook(() => usePreview("flat-lay-01", null, "bundled-grid"));

    await new Promise((resolve) => setTimeout(resolve, 250));
    expect(spy).not.toHaveBeenCalled();
    expect(result.current).toBeNull();
  });

  it("does not re-request when the body is rebuilt with equal values", async () => {
    const spy = vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:one");
    const { result, rerender } = renderHook(() =>
      // A fresh object literal every render, as an editor produces.
      usePreview("lifestyle-01", { ...BODY }, "bundled-grid"),
    );
    await waitFor(() => expect(result.current).toBe("blob:one"));

    rerender();
    rerender();
    await new Promise((resolve) => setTimeout(resolve, 250));
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("keeps the last good preview on screen when a render fails", async () => {
    vi.spyOn(calibrator, "renderPreview")
      .mockResolvedValueOnce("blob:one")
      .mockRejectedValueOnce(new Error("preview failed"));
    const { result, rerender } = renderHook(
      ({ design }) => usePreview("lifestyle-01", BODY, design),
      { initialProps: { design: "bundled-grid" } },
    );
    await waitFor(() => expect(result.current).toBe("blob:one"));

    rerender({ design: "bundled-on-dark" });
    await new Promise((resolve) => setTimeout(resolve, 250));
    expect(result.current).toBe("blob:one");
  });
});

describe("usePreview's one-at-a-time rule", () => {
  it("coalesces edits made during a render into a single follow-up", async () => {
    let release: (url: string) => void = () => {};
    const spy = vi
      .spyOn(calibrator, "renderPreview")
      .mockImplementationOnce(() => new Promise<string>((resolve) => (release = resolve)))
      .mockResolvedValue("blob:final");

    const { result, rerender } = renderHook(
      ({ design }) => usePreview("flat-lay-01", BODY, design),
      {
        initialProps: { design: "d0" },
      },
    );
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));

    // Three edits while the first render is still out. None of them may be
    // sent -- queueing them would make every frame arrive later than the last.
    for (const design of ["d1", "d2", "d3"]) rerender({ design });
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(spy).toHaveBeenCalledTimes(1);

    release("blob:first");
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    // The newest, not the oldest of the three.
    expect(spy).toHaveBeenLastCalledWith("flat-lay-01", BODY, "d3", "editor");
    await waitFor(() => expect(result.current).toBe("blob:final"));
  });

  it("drops a render that lands after the editor has moved to another template", async () => {
    let release: (url: string) => void = () => {};
    vi.spyOn(calibrator, "renderPreview")
      .mockImplementationOnce(() => new Promise<string>((resolve) => (release = resolve)))
      .mockResolvedValue("blob:other");

    const { result, rerender } = renderHook(({ name }) => usePreview(name, BODY, "bundled-grid"), {
      initialProps: { name: "flat-lay-01" },
    });
    await new Promise((resolve) => setTimeout(resolve, 150));

    rerender({ name: "lifestyle-01" });
    release("blob:stale");

    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:stale"));
    expect(result.current).not.toBe("blob:stale");
  });
});
