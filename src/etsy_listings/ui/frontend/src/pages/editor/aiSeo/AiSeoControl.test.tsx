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
      { label: "SEO prompt and AI provider ready", ready: false },
    ],
    reason: null,
    phase: "idle",
    proposal: null,
    stale: false,
    generate: vi.fn(),
    draftsBrief: false,
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
    expect(card).toHaveTextContent("SEO prompt and AI provider ready");
    expect(card).not.toHaveTextContent("Brief filled in");
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
    expect(screen.getByRole("tooltip")).not.toHaveTextContent("Writes a brief");
    expect(screen.getByRole("tooltip")).not.toHaveTextContent("Design selected");
  });

  it("says an empty brief will be written before the suggestions", () => {
    render(<AiSeoControl mode={mode({ draftsBrief: true })} />);
    expect(screen.getByRole("tooltip")).toHaveTextContent(
      "Writes a brief from this design, then generates title, description and tag recommendations",
    );
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

  it("names what failed in a toast, and leaves the timer row as Try again", () => {
    render(
      <AiSeoControl
        mode={mode({ phase: "failed", failure: "Etsy market search failed: timed out" })}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "AI Mode couldn’t finish: Etsy market search failed: timed out",
    );
    expect(screen.getByRole("button", { name: "Try again" }).parentElement).not.toHaveTextContent(
      "timed out",
    );
  });

  it("shows Try again without the failure sentence beside it, and leaves AI Mode enabled", () => {
    const generate = vi.fn();
    render(<AiSeoControl mode={mode({ phase: "failed", generate })} />);

    const again = screen.getByRole("button", { name: "Try again" });
    expect(again.parentElement).not.toHaveTextContent(/couldn/i);
    expect(screen.getByRole("alert")).toHaveTextContent(/couldn.t generate/i);
    expect(screen.getByRole("button", { name: /AI Mode/i })).toBeEnabled();

    fireEvent.click(again);
    expect(generate).toHaveBeenCalled();
  });

  it("does not announce a run the AI Mode button started", () => {
    render(
      <AiSeoControl mode={mode({ phase: "loading", run: aiRunStub({ autoNotice: false }) })} />,
    );

    expect(
      screen.queryByText("AI Mode is writing a title, tags and a description from this design."),
    ).toBeNull();
  });

  it("dismisses the toast and keeps Try again", () => {
    render(<AiSeoControl mode={mode({ phase: "failed", failure: "timed out" })} />);

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("forwards a ref to the AI Mode button so focus can return to it", () => {
    const ref = createRef<HTMLButtonElement>();
    render(<AiSeoControl mode={mode()} buttonRef={ref} />);
    expect(ref.current).toBe(screen.getByRole("button", { name: /AI Mode/i }));
  });
});
