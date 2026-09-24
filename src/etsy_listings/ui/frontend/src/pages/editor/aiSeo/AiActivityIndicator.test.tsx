import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { AiActivityIndicator } from "./AiActivityIndicator";
import type { AiSeoMode } from "./useAiSeoMode";
import type { AutoDesignBrief } from "./useAutoDesignBrief";

/** The page head's one line while PRD 68's chain runs. Its whole job is
 * telling a seller who is looking at Variants what attaching a design set
 * going, so every test here is "which of the two messages, and is it
 * announced politely". */

function aiSeo(over: Partial<AiSeoMode> = {}): AiSeoMode {
  return {
    available: true,
    requirements: [],
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

function auto(over: Partial<AutoDesignBrief> = {}): AutoDesignBrief {
  return { phase: "idle", start: vi.fn(), ...over };
}

function show(autoState: AutoDesignBrief, seoState: AiSeoMode) {
  return render(<AiActivityIndicator auto={autoState} aiSeo={seoState} />);
}

it("says nothing at all in the ordinary case", () => {
  const { container } = show(auto(), aiSeo());

  expect(container).toBeEmptyDOMElement();
});

it("reports the brief being drafted", () => {
  show(auto({ phase: "drafting" }), aiSeo());

  expect(screen.getByRole("status")).toHaveTextContent("Generating brief…");
});

it("reports SEO generation once the brief has landed", () => {
  show(auto(), aiSeo({ phase: "loading" }));

  expect(screen.getByRole("status")).toHaveTextContent("Generating SEO…");
});

it("names the step that is actually running when both could claim the line", () => {
  /* Only the brief step can overlap generation in principle -- the chain
     starts one from the other -- and the brief is the earlier of the two, so
     it wins. Saying "Generating SEO" while the brief is still being read
     would name a step that has not begun. */
  show(auto({ phase: "drafting" }), aiSeo({ phase: "loading" }));

  expect(screen.getByRole("status")).toHaveTextContent("Generating brief…");
});

it("says nothing for a failed draft, which is not activity", () => {
  const { container } = show(auto({ phase: "failed" }), aiSeo());

  expect(container).toBeEmptyDOMElement();
});

it("announces politely, once", () => {
  show(auto({ phase: "drafting" }), aiSeo());

  const region = screen.getByRole("status");
  expect(region).toHaveAttribute("aria-live", "polite");
  expect(screen.getAllByRole("status")).toHaveLength(1);
});
