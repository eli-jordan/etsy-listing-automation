import type { BatchResult } from "./batchDeployPresentation";

/** Where the all-listings page is: still planning, applying, showing an
 * apply's result, or holding a plan up for review. */
export type BatchStage = "planning" | "applying" | "applied" | "review";

export function batchStage(flags: {
  planning: boolean;
  applying: boolean;
  terminalApply: boolean;
}): BatchStage {
  if (flags.planning) return "planning";
  if (flags.applying) return "applying";
  return flags.terminalApply ? "applied" : "review";
}

export const BATCH_STAGE_TITLES: Record<BatchStage, string> = {
  planning: "Planning all listings…",
  applying: "Applying all changes…",
  applied: "Batch result",
  review: "Review all changes",
};

/** An apply result someone has to act on: partial, failed or stale. */
export function resultNeedsAttention(result: BatchResult): boolean {
  return result.partial || result.failed.length > 0 || result.stale.length > 0;
}

export function resultTone(result: BatchResult): "drift" | "blocked" | "ok" {
  if (result.partial) return "drift";
  return resultNeedsAttention(result) ? "blocked" : "ok";
}

export function resultHeadline(result: BatchResult): string {
  if (result.partial) return "Batch partially applied.";
  if (result.stale.length > 0) return "Some listings became stale.";
  if (result.failed.length > 0) return "Batch apply failed.";
  return "All planned work finished.";
}

export interface FooterFacts {
  stage: BatchStage;
  result: BatchResult;
  /** The plan is ready and has work an apply would run. */
  canApply: boolean;
  previewsReady: boolean;
  readyPreviews: number;
  requiredPreviews: number;
  nothingToDo: boolean;
}

const APPLY_RUNS_THE_PLAN = "Apply runs exactly this plan, one listing at a time.";

/** The footer's line beside its one action. */
export function batchFooterMessage(facts: FooterFacts): string {
  if (facts.stage === "applying") return APPLY_RUNS_THE_PLAN;
  if (facts.stage === "applied") {
    return resultNeedsAttention(facts.result)
      ? "Review the affected listings, then plan again for the remaining work."
      : "All planned work finished.";
  }
  if (facts.canApply) {
    if (facts.previewsReady) return APPLY_RUNS_THE_PLAN;
    return `Preview images before applying (${facts.readyPreviews} of ${facts.requiredPreviews})…`;
  }
  return facts.nothingToDo
    ? "No remote changes were found."
    : "Apply unlocks once the reviewed previews are ready.";
}
