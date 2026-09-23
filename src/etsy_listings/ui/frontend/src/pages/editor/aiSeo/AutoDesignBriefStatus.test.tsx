import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { SeoProposalResponse } from "../../../types";
import { AutoDesignBriefStatus } from "./AutoDesignBriefStatus";
import type { AiSeoMode } from "./useAiSeoMode";
import type { AutoDesignBrief } from "./useAutoDesignBrief";

/** The design strip's one line while PRD 68's chain runs. Its whole job is
 * telling a seller on **Variants** what attaching a design just set going,
 * so every test here is "which sentence, and is there a way back to the
 * field it is about". */

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
  return { phase: "idle", waiting: false, ...over };
}

function storedProposal() {
  return {
    proposal: {} as SeoProposalResponse,
    unresolved: { title: true, tags: true, lead: true },
  };
}

function show(autoState: AutoDesignBrief, seoState: AiSeoMode, onOpenDetails = vi.fn()) {
  render(<AutoDesignBriefStatus auto={autoState} aiSeo={seoState} onOpenDetails={onOpenDetails} />);
  return onOpenDetails;
}

it("says nothing at all in the ordinary case", () => {
  const { container } = render(
    <AutoDesignBriefStatus auto={auto()} aiSeo={aiSeo()} onOpenDetails={vi.fn()} />,
  );

  expect(container).toBeEmptyDOMElement();
});

it("asks for a name while the chain waits on an unsaved draft", () => {
  show(auto({ waiting: true }), aiSeo());

  expect(screen.getByRole("status")).toHaveTextContent(/save this listing/i);
});

it("reports the brief being drafted from the design", () => {
  show(auto({ phase: "drafting" }), aiSeo());

  expect(screen.getByRole("status")).toHaveTextContent(/draft a brief/i);
});

it("reports generation once the brief has landed", () => {
  show(auto(), aiSeo({ phase: "loading" }));

  expect(screen.getByRole("status")).toHaveTextContent(/SEO suggestions/i);
});

it("offers the way to the drawers once suggestions are waiting", () => {
  const open = show(auto(), aiSeo({ proposal: storedProposal() }));

  fireEvent.click(screen.getByRole("button", { name: "Open Listing Details" }));

  expect(open).toHaveBeenCalled();
});

it("says nothing about a stale proposal, which is not ready to review", () => {
  const { container } = render(
    <AutoDesignBriefStatus
      auto={auto()}
      aiSeo={aiSeo({ proposal: storedProposal(), stale: true })}
      onOpenDetails={vi.fn()}
    />,
  );

  expect(container).toBeEmptyDOMElement();
});

it("points at the Brief field when drafting failed, and does not offer a retry", () => {
  const open = show(auto({ phase: "failed" }), aiSeo());

  expect(screen.getByRole("status")).toHaveTextContent(/write one in listing details/i);
  expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Open Listing Details" }));
  expect(open).toHaveBeenCalled();
});

it("keeps its messages in one polite live region", () => {
  show(auto({ phase: "drafting" }), aiSeo());

  const region = screen.getByRole("status");
  expect(region).toHaveAttribute("aria-live", "polite");
  expect(screen.getAllByRole("status")).toHaveLength(1);
});
