import type { BatchResult } from "./batchDeployPresentation";

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
  canApply: boolean;
  previewsReady: boolean;
  readyPreviews: number;
  requiredPreviews: number;
  nothingToDo: boolean;
}

const APPLY_RUNS_THE_PLAN = "Apply runs exactly this plan, one listing at a time.";

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
