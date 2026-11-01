import { describe, expect, it } from "vitest";
import type { BatchResult } from "./batchDeployPresentation";
import {
  batchFooterMessage,
  batchStage,
  resultHeadline,
  resultNeedsAttention,
  resultTone,
  type FooterFacts,
} from "./batchDeployView";

function result(overrides: Partial<BatchResult> = {}): BatchResult {
  return {
    terminal: true,
    succeeded: [],
    clean: [],
    failed: [],
    stale: [],
    blocked: [],
    attention: [],
    pending: [],
    partial: false,
    ...overrides,
  };
}

describe("batchStage", () => {
  it("names each stage from the page's flags", () => {
    const flags = { planning: false, applying: false, terminalApply: false };
    expect(batchStage({ ...flags, planning: true })).toBe("planning");
    expect(batchStage({ ...flags, applying: true })).toBe("applying");
    expect(batchStage({ ...flags, terminalApply: true })).toBe("applied");
    expect(batchStage(flags)).toBe("review");
  });
});

describe("batch result callout", () => {
  it("calls a partial apply drift, ahead of failures", () => {
    const partial = result({ partial: true, succeeded: ["a"], failed: ["b"] });
    expect(resultTone(partial)).toBe("drift");
    expect(resultHeadline(partial)).toBe("Batch partially applied.");
    expect(resultNeedsAttention(partial)).toBe(true);
  });

  it("names stale before failed, both blocked", () => {
    const both = result({ stale: ["a"], failed: ["b"] });
    expect(resultTone(both)).toBe("blocked");
    expect(resultHeadline(both)).toBe("Some listings became stale.");
    expect(resultHeadline(result({ failed: ["b"] }))).toBe("Batch apply failed.");
    expect(resultTone(result({ failed: ["b"] }))).toBe("blocked");
  });

  it("is ok and quiet when everything finished", () => {
    const clean = result({ succeeded: ["a"] });
    expect(resultTone(clean)).toBe("ok");
    expect(resultHeadline(clean)).toBe("All planned work finished.");
    expect(resultNeedsAttention(clean)).toBe(false);
  });
});

describe("batchFooterMessage", () => {
  const facts: FooterFacts = {
    stage: "review",
    result: result(),
    canApply: false,
    previewsReady: true,
    readyPreviews: 0,
    requiredPreviews: 0,
    nothingToDo: false,
  };

  it("describes an apply in flight", () => {
    expect(batchFooterMessage({ ...facts, stage: "applying" })).toBe(
      "Apply runs exactly this plan, one listing at a time.",
    );
  });

  it("points at the remaining work after an apply that needs attention", () => {
    expect(
      batchFooterMessage({ ...facts, stage: "applied", result: result({ failed: ["a"] }) }),
    ).toBe("Review the affected listings, then plan again for the remaining work.");
    expect(batchFooterMessage({ ...facts, stage: "applied" })).toBe("All planned work finished.");
  });

  it("counts previews still rendering before an apply", () => {
    expect(batchFooterMessage({ ...facts, canApply: true })).toBe(
      "Apply runs exactly this plan, one listing at a time.",
    );
    expect(
      batchFooterMessage({
        ...facts,
        canApply: true,
        previewsReady: false,
        readyPreviews: 1,
        requiredPreviews: 3,
      }),
    ).toBe("Preview images before applying (1 of 3)…");
  });

  it("says why apply is unavailable otherwise", () => {
    expect(batchFooterMessage({ ...facts, nothingToDo: true })).toBe(
      "No remote changes were found.",
    );
    expect(batchFooterMessage(facts)).toBe("Apply unlocks once the reviewed previews are ready.");
  });
});
