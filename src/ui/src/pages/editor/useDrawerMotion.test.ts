import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useDrawerMotion } from "./useDrawerMotion";

afterEach(() => vi.restoreAllMocks());

function render(phase: string | null, hasProposal: boolean) {
  return renderHook(({ phase, hasProposal }) => useDrawerMotion(phase, hasProposal), {
    initialProps: { phase, hasProposal },
  });
}

describe("useDrawerMotion", () => {
  it("is still on first render, even with a proposal already there", () => {
    expect(render("idle", true).result.current).toBe(false);
  });

  it("animates the drawers a finished request opens on a visible tab", () => {
    const hook = render("loading", false);
    hook.rerender({ phase: "idle", hasProposal: true });
    expect(hook.result.current).toBe(true);
  });

  it("stays still when the request finished on a hidden tab", () => {
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    const hook = render("loading", false);
    hook.rerender({ phase: "idle", hasProposal: true });
    expect(hook.result.current).toBe(false);
  });

  it("stays still for a phase change that was not the end of a request", () => {
    const hook = render("idle", true);
    hook.rerender({ phase: "failed", hasProposal: true });
    expect(hook.result.current).toBe(false);
  });

  it("stops once the proposal is resolved", () => {
    const hook = render("loading", false);
    hook.rerender({ phase: "idle", hasProposal: true });
    hook.rerender({ phase: "idle", hasProposal: false });
    expect(hook.result.current).toBe(false);
  });
});
