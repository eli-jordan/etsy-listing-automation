import { createRef } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { aiRunStub } from "../../../test/aiRuns";
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
    failure: null,
    startedAt: null,
    run: aiRunStub(),
    market: null,
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

afterEach(() => {
  vi.useRealTimers();
});

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
    expect(screen.getByRole("tooltip")).toHaveTextContent(
      "Generates SEO fields using AI (title, description lead and tags)",
    );
    expect(screen.getByRole("tooltip")).not.toHaveTextContent("Design selected");
  });

  it("calls generate() when AI Mode is activated", () => {
    const generate = vi.fn();
    render(<AiSeoControl mode={mode({ generate })} />);
    fireEvent.click(screen.getByRole("button", { name: /AI Mode/i }));
    expect(generate).toHaveBeenCalled();
  });

  it("shows a polite loading status with Cancel while generating, and disables AI Mode", () => {
    vi.useFakeTimers();
    const cancel = vi.fn();
    render(<AiSeoControl mode={mode({ phase: "loading", cancel, startedAt: Date.now() })} />);

    expect(screen.getByRole("tooltip", { hidden: true })).toHaveTextContent(
      "Generating title, description and tag recommendations for your review",
    );
    const button = screen.getByRole("button", { name: /AI Mode/i });
    expect(button).toBeDisabled();
    expect(button).toHaveClass("seo-ai-mode--busy");
    expect(screen.getByText("Generating for 0:00 seconds")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByText("Generating for 0:03 seconds")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(cancel).toHaveBeenCalled();
  });

  it("counts from the run's own start, so a reload mid-run keeps counting", () => {
    vi.useFakeTimers();
    render(<AiSeoControl mode={mode({ phase: "loading", startedAt: Date.now() - 65_000 })} />);

    expect(screen.getByText("Generating for 1:05 seconds")).toBeInTheDocument();
  });

  it("names what failed when the run says", () => {
    render(
      <AiSeoControl
        mode={mode({ phase: "failed", failure: "Etsy market search failed: timed out" })}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "AI Mode couldn’t finish: Etsy market search failed: timed out",
    );
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
