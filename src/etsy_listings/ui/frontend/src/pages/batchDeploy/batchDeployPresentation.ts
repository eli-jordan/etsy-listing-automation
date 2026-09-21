import {
  stageBlocked,
  stageWillRun,
  type ListingSummary,
  type PlanDTO,
  type StagePlanDTO,
} from "../../types";
import { buildComparison, type ImpactTag } from "../deploy/comparison";
import type { StageRuntimeStatus } from "../deploy/deployState";
import type { BatchDeployState, BatchListingState } from "./batchDeployState";

export type BatchPlanGroup = "add" | "change" | "remove" | "attention";

export interface CandidateNames {
  add: string[];
  edit: string[];
  remove: string[];
}

export interface CandidateCounts {
  add: number;
  edit: number;
  remove: number;
}

export function candidateNames(summaries: readonly ListingSummary[]): CandidateNames {
  const names: CandidateNames = { add: [], edit: [], remove: [] };
  for (const summary of summaries) {
    const hasEtsyListing =
      summary.etsy_listing_id !== null && summary.etsy_listing_id !== undefined;
    if (summary.status === "pending-delete") {
      names.remove.push(summary.name);
    } else if (summary.status === "draft" && !hasEtsyListing) {
      names.add.push(summary.name);
    } else if (
      summary.status === "dirty" ||
      (summary.status === "draft" && hasEtsyListing) ||
      // Normal table gestures (delete, retire, renew) are lifecycle actions,
      // not evidence that the deploy plan has local work to review.
      summary.status === "pending-retire"
    ) {
      names.edit.push(summary.name);
    }
  }
  return names;
}

export function candidateCounts(summaries: readonly ListingSummary[]): CandidateCounts {
  const names = candidateNames(summaries);
  return { add: names.add.length, edit: names.edit.length, remove: names.remove.length };
}

function hasBlockedStage(plan: PlanDTO): boolean {
  return plan.stage_plans.some((stage) => stageBlocked(stage) !== null);
}

function hasRunnableStage(plan: PlanDTO): boolean {
  return plan.stage_plans.some(stageWillRun);
}

export function planGroup(plan: PlanDTO | null, planFailure: string | null = null): BatchPlanGroup {
  if (
    plan === null ||
    planFailure !== null ||
    (plan !== null && !hasRunnableStage(plan) && hasBlockedStage(plan))
  ) {
    return "attention";
  }
  if (plan.stage_plans.some((stage) => stage.stage === "retract")) return "remove";
  if (plan.etsy_listing_id === null) return "add";
  return "change";
}

export function buyerFacingImpacts(plan: PlanDTO): ImpactTag[] {
  return buildComparison(plan).impacts;
}

/** Returned pipeline order is authoritative for the first occurrence of each
 * stage. Retraction is a disjoint lifecycle operation, so it is always shown
 * after the normal pipeline even if a future backend emits it earlier. */
export function aggregateStageOrder(plans: readonly PlanDTO[]): string[] {
  const normal: string[] = [];
  let hasRetract = false;
  for (const plan of plans) {
    for (const stage of plan.stage_plans) {
      if (stage.stage === "retract") {
        hasRetract = true;
      } else if (!normal.includes(stage.stage)) {
        normal.push(stage.stage);
      }
    }
  }
  return hasRetract ? [...normal, "retract"] : normal;
}

export interface StageProgress {
  total: number;
  completed: number;
  running: number;
  failed: number;
}

function runtimeProgress(
  stagePlan: StagePlanDTO | undefined,
  runtime: StageRuntimeStatus | undefined,
): StageProgress {
  if (stagePlan === undefined || !stageWillRun(stagePlan)) {
    return { total: 0, completed: 0, running: 0, failed: 0 };
  }
  return {
    total: 1,
    completed: runtime?.kind === "applied" ? 1 : 0,
    running: runtime?.kind === "applying" ? 1 : 0,
    failed: runtime?.kind === "failed" ? 1 : 0,
  };
}

export function listingStageProgress(
  plan: PlanDTO,
  stageRuntime: Record<string, StageRuntimeStatus>,
  stage: string,
): StageProgress {
  return runtimeProgress(
    plan.stage_plans.find((candidate) => candidate.stage === stage),
    stageRuntime[stage],
  );
}

export function aggregateStageProgress(
  plans: readonly PlanDTO[],
  listings: readonly BatchListingState[],
  stage: string,
): StageProgress {
  const states = new Map(listings.map((listing) => [listing.listing, listing]));
  return plans.reduce<StageProgress>(
    (total, plan) => {
      const progress = listingStageProgress(
        plan,
        states.get(plan.listing)?.stageRuntime ?? {},
        stage,
      );
      return {
        total: total.total + progress.total,
        completed: total.completed + progress.completed,
        running: total.running + progress.running,
        failed: total.failed + progress.failed,
      };
    },
    { total: 0, completed: 0, running: 0, failed: 0 },
  );
}

export interface BatchResult {
  terminal: boolean;
  succeeded: string[];
  clean: string[];
  failed: string[];
  stale: string[];
  blocked: string[];
  attention: string[];
  pending: string[];
  partial: boolean;
}

const TERMINAL_PHASES = new Set(["applied", "failed", "stale", "cancelled"]);

function planIsClean(plan: PlanDTO): boolean {
  return plan.stage_plans.every((stage) => !stageWillRun(stage) && stageBlocked(stage) === null);
}

function planIsBlocked(plan: PlanDTO): boolean {
  return !hasRunnableStage(plan) && hasBlockedStage(plan);
}

function allRunnableStagesApplied(listing: BatchListingState): boolean {
  return (
    listing.plan !== null &&
    listing.plan.stage_plans
      .filter(stageWillRun)
      .every((stage) => listing.stageRuntime[stage.stage]?.kind === "applied")
  );
}

export function batchResult(state: BatchDeployState): BatchResult {
  const terminal = state.applyStarted && TERMINAL_PHASES.has(state.phase);
  const result: BatchResult = {
    terminal,
    succeeded: [],
    clean: [],
    failed: [],
    stale: [],
    blocked: [],
    attention: [],
    pending: [],
    partial: false,
  };

  for (const [name, listing] of Object.entries(state.listings)) {
    if (listing.stale) {
      result.stale.push(name);
    } else if (listing.plan === null || listing.planFailure !== null) {
      result.attention.push(name);
    } else if (listing.failureMessage !== null) {
      result.failed.push(name);
    } else if (planIsBlocked(listing.plan)) {
      result.blocked.push(name);
    } else if (planIsClean(listing.plan)) {
      result.clean.push(name);
      if (terminal) result.succeeded.push(name);
      else result.pending.push(name);
    } else if (allRunnableStagesApplied(listing)) {
      result.succeeded.push(name);
    } else {
      result.pending.push(name);
    }
  }

  result.attention.push(...result.failed, ...result.stale, ...result.blocked);
  result.partial =
    terminal &&
    result.succeeded.length > 0 &&
    (result.failed.length > 0 || result.stale.length > 0);
  return result;
}
