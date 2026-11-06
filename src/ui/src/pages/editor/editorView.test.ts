import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { isString, SCROLL_RESTORE_MS, useViewScroll, useViewState, viewScope } from "./editorView";

/** The hook as an editor mounts it; unmounting and calling this again is what
 * a page refresh does to it. */
function mount(scope: string | null, fallback = "variants") {
  return renderHook(
    ({ current }: { current: string | null }) => useViewState(current, "tab", fallback, isString),
    { initialProps: { current: scope } },
  );
}

describe("viewScope", () => {
  it("names a saved editor, and gives an unnamed draft nothing to come back to", () => {
    expect(viewScope("listing", "take-a-hike")).toBe("listing:take-a-hike");
    expect(viewScope("listing-template", "take-a-hike")).toBe("listing-template:take-a-hike");
    expect(viewScope("listing", "")).toBeNull();
  });
});

describe("useViewState", () => {
  it("opens on the fallback when nothing is remembered", () => {
    expect(mount("listing:a").result.current[0]).toBe("variants");
  });

  it("comes back to the value after a remount", () => {
    const first = mount("listing:a");
    act(() => first.result.current[1]("images"));
    first.unmount();

    expect(mount("listing:a").result.current[0]).toBe("images");
  });

  it("keeps each listing's view apart", () => {
    const first = mount("listing:a");
    act(() => first.result.current[1]("images"));
    first.unmount();

    expect(mount("listing:b").result.current[0]).toBe("variants");
  });

  it("remembers nothing without a scope", () => {
    const first = mount(null);
    act(() => first.result.current[1]("images"));
    first.unmount();

    expect(sessionStorage).toHaveLength(0);
    expect(mount(null).result.current[0]).toBe("variants");
  });

  it("carries a draft's view across to the name it gets", () => {
    const draft = mount(null);
    act(() => draft.result.current[1]("images"));
    draft.rerender({ current: "listing:a" });
    draft.unmount();

    expect(mount("listing:a").result.current[0]).toBe("images");
  });

  it("falls back on a value it does not accept", () => {
    sessionStorage.setItem("editor-view:listing:a:tab", "42");
    expect(mount("listing:a").result.current[0]).toBe("variants");
  });

  it("falls back on a value that is not JSON", () => {
    sessionStorage.setItem("editor-view:listing:a:tab", "{not json");
    expect(mount("listing:a").result.current[0]).toBe("variants");
  });

  it("still works when storage refuses the write", () => {
    const refused = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("full", "QuotaExceededError");
    });
    const { result } = mount("listing:a");

    act(() => result.current[1]("images"));

    expect(result.current[0]).toBe("images");
    refused.mockRestore();
  });
});

describe("useViewScroll", () => {
  const KEY = "editor-view:listing:a:scroll";
  let frames: FrameRequestCallback[];
  let scrollTo: ReturnType<typeof vi.fn>;
  let now: number;

  /** How tall the page is, as far as the hook can tell. */
  function pageHeight(height: number) {
    Object.defineProperty(document.documentElement, "scrollHeight", {
      configurable: true,
      value: height,
    });
  }

  function nextFrame() {
    const queued = frames;
    frames = [];
    queued.forEach((frame) => frame(now));
  }

  beforeEach(() => {
    frames = [];
    now = 0;
    scrollTo = vi.fn();
    vi.spyOn(performance, "now").mockImplementation(() => now);
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((frame) => frames.push(frame));
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {
      frames = [];
    });
    window.scrollTo = scrollTo as unknown as typeof window.scrollTo;
    pageHeight(0);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    Reflect.deleteProperty(document.documentElement, "scrollHeight");
    Object.defineProperty(window, "scrollY", { configurable: true, value: 0 });
  });

  it("waits for the page to be tall enough, then returns to where it was", () => {
    sessionStorage.setItem(KEY, "600");
    renderHook(() => useViewScroll("listing:a"));

    nextFrame();
    expect(scrollTo).not.toHaveBeenCalled();

    pageHeight(600 + window.innerHeight);
    nextFrame();
    expect(scrollTo).toHaveBeenCalledWith(0, 600);
    expect(frames).toHaveLength(0);
  });

  it("does nothing when there is nowhere to return to", () => {
    renderHook(() => useViewScroll("listing:a"));
    expect(frames).toHaveLength(0);
    expect(scrollTo).not.toHaveBeenCalled();
  });

  it("gives up when the page never grows that tall", () => {
    sessionStorage.setItem(KEY, "600");
    renderHook(() => useViewScroll("listing:a"));

    now = SCROLL_RESTORE_MS;
    nextFrame();

    expect(frames).toHaveLength(0);
    expect(scrollTo).not.toHaveBeenCalled();
  });

  it("leaves the page alone once the seller scrolls it themselves", () => {
    sessionStorage.setItem(KEY, "600");
    renderHook(() => useViewScroll("listing:a"));

    window.dispatchEvent(new Event("wheel"));
    pageHeight(600 + window.innerHeight);
    nextFrame();

    expect(scrollTo).not.toHaveBeenCalled();
  });

  it("remembers where the page is scrolled to", () => {
    renderHook(() => useViewScroll("listing:a"));

    Object.defineProperty(window, "scrollY", { configurable: true, value: 420 });
    window.dispatchEvent(new Event("scroll"));

    expect(sessionStorage.getItem(KEY)).toBe("420");
  });

  it("keeps the remembered position while it is still waiting to return", () => {
    sessionStorage.setItem(KEY, "600");
    renderHook(() => useViewScroll("listing:a"));

    window.dispatchEvent(new Event("scroll"));

    expect(sessionStorage.getItem(KEY)).toBe("600");
  });

  it("remembers nothing without a scope", () => {
    renderHook(() => useViewScroll(null));

    window.dispatchEvent(new Event("scroll"));

    expect(sessionStorage).toHaveLength(0);
  });

  it("stops listening when the editor closes", () => {
    sessionStorage.setItem(KEY, "600");
    const { unmount } = renderHook(() => useViewScroll("listing:a"));

    unmount();
    expect(frames).toHaveLength(0);

    Object.defineProperty(window, "scrollY", { configurable: true, value: 10 });
    window.dispatchEvent(new Event("scroll"));
    expect(sessionStorage.getItem(KEY)).toBe("600");
  });
});
