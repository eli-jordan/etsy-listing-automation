import { createRef } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AiSeoControl } from "./AiSeoControl";
import type { AiSeoMode } from "./useAiSeoMode";

function mode(over: Partial<AiSeoMode> = {}): AiSeoMode {
  return {
    available: true,
    requirements: [
      { label: "Saved listing", ready: true },
      { label: "Design selected", ready: false },
      { label: "Brief filled in", ready: false },
    ],
    reason: null,
    phase: "idle",
    proposal: null,
    stale: false,
    generate: vi.fn(),
    cancel: vi.fn(),
    chooseTitle: vi.fn(),
    rejectTitle: vi.fn(),
    chooseLead: vi.fn(),
    rejectLead: vi.fn(),
    toggleTag: vi.fn(),
    acceptBestTags: vi.fn(),
    closeTags: vi.fn(),
    ...over,
  };
}

describe("AiSeoControl", () => {
  it("renders a disabled AI Mode button when unavailable", () => {
    render(<AiSeoControl mode={mode({ available: false })} />);
    expect(screen.getByRole("button", { name: /AI Mode/i })).toBeDisabled();
  });

  it("explains the missing fields and setup reason on the hover card", () => {
    render(<AiSeoControl mode={mode({ available: false, reason: "No AI provider is ready." })} />);
    const card = screen.getByRole("tooltip");
    expect(card).toHaveTextContent("Design selected");
    expect(card).toHaveTextContent("Brief filled in");
    expect(card).toHaveTextContent("No AI provider is ready.");
    expect(screen.getByRole("button", { name: /AI Mode/i })).toHaveAttribute(
      "aria-describedby",
      card.id,
    );
  });

  it("renders an enabled AI Mode button when ready and idle", () => {
    render(<AiSeoControl mode={mode()} />);
    const button = screen.getByRole("button", { name: /AI Mode/i });
    expect(button).toBeEnabled();
  });

  it("calls generate() when AI Mode is activated", () => {
    const generate = vi.fn();
    render(<AiSeoControl mode={mode({ generate })} />);
    fireEvent.click(screen.getByRole("button", { name: /AI Mode/i }));
    expect(generate).toHaveBeenCalled();
  });

  it("shows a polite loading status with Cancel while generating, and disables AI Mode", () => {
    const cancel = vi.fn();
    render(<AiSeoControl mode={mode({ phase: "loading", cancel })} />);

    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveTextContent(/generating/i);
    expect(screen.getByRole("button", { name: /AI Mode/i })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(cancel).toHaveBeenCalled();
  });

  it("shows a failure message with Try again, and leaves AI Mode enabled", () => {
    const generate = vi.fn();
    render(<AiSeoControl mode={mode({ phase: "failed", generate })} />);

    expect(screen.getByRole("status")).toHaveTextContent(/couldn.t generate/i);
    expect(screen.getByRole("button", { name: /AI Mode/i })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(generate).toHaveBeenCalled();
  });

  it("forwards a ref to the AI Mode button so focus can return to it", () => {
    const ref = createRef<HTMLButtonElement>();
    render(<AiSeoControl mode={mode()} buttonRef={ref} />);
    expect(ref.current).toBe(screen.getByRole("button", { name: /AI Mode/i }));
  });
});
