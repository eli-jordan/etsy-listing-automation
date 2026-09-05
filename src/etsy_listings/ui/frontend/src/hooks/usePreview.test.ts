import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../api/calibrator";
import { usePreview } from "./usePreview";

const BODY = {
  bounding_box: [
    { x: 0, y: 0 },
    { x: 100, y: 0 },
    { x: 100, y: 100 },
    { x: 0, y: 100 },
  ],
  displace: { enabled: false, strength: 0 },
  shade: { enabled: true, opacity: 0.6, blend: "soft-light" },
} as Parameters<typeof usePreview>[1];

beforeEach(() => {
  vi.mocked(URL.revokeObjectURL).mockClear();
});

afterEach(() => vi.restoreAllMocks());

describe("usePreview", () => {
  it("fetches a preview and returns its object URL", async () => {
    const spy = vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:one");
    const { result } = renderHook(() => usePreview("lifestyle-01", BODY, "bundled-grid"));

    await waitFor(() => expect(result.current).toBe("blob:one"));
    expect(spy).toHaveBeenCalledWith("lifestyle-01", BODY, "bundled-grid");
  });

  it("revokes the displayed object URL when the editor unmounts", async () => {
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:one");
    const { result, unmount } = renderHook(() =>
      usePreview("lifestyle-01", BODY, "bundled-grid"),
    );
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
