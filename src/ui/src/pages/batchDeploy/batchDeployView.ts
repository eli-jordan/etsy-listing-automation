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

/** The words that differ between a deploy of every listing and one of a
 * listing batch's reviewed rows (ADR-0059); everything else on the page is
 * the same. */
export interface ScopeCopy {
  scope: "workspace" | "batch";
  noun: string;
  plan: string;
  across: string;
  back: string;
  returnTo: string;
  planRefused: string;
}

const SCOPE_COPY: Record<ScopeCopy["scope"], ScopeCopy> = {
  workspace: {
    scope: "workspace",
    noun: "workspace",
    plan: "all-listings plan",
    across: "across this workspace",
    back: "← Back to listings",
    returnTo: "return to Listings",
    planRefused: "Could not start a fresh workspace plan.",
  },
  batch: {
    scope: "batch",
    noun: "batch",
    plan: "batch plan",
    across: "for the reviewed listings in this batch",
    back: "← Back to batch",
    returnTo: "return to the batch",
    planRefused:
      "Could not start a fresh batch plan. There may be no reviewed listings left to deploy.",
  },
};

/** The page's words for a run of listing batch `batchId`, or of the whole
 * workspace when `null`. */
export function scopeCopy(batchId: string | null): ScopeCopy {
  return SCOPE_COPY[batchId === null ? "workspace" : "batch"];
}

const BATCH_SCOPE_TITLES: Record<BatchStage, string> = {
  planning: "Planning reviewed listings…",
  applying: "Applying reviewed changes…",
  applied: "Batch result",
  review: "Review batch changes",
};

export function batchStageTitle(stage: BatchStage, copy: ScopeCopy): string {
  return (copy.scope === "batch" ? BATCH_SCOPE_TITLES : BATCH_STAGE_TITLES)[stage];
}

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
