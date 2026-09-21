import type { RunDetail, RunEvent, RunKind, RunPhase, RunSummary, StagePlanDTO } from "../types";

/** Narrows away `undefined`/`null` in tests without the `!` non-null
 * assertion operator (forbidden by this repo's eslint config) -- throws with
 * a clear message if the value genuinely isn't there, which is a better
 * failure than a silent `undefined` propagating into an assertion. */
export function must<T>(value: T | undefined | null): T {
  if (value === undefined || value === null) {
    throw new Error("expected a defined value in test");
  }
  return value;
}

type StageName = StagePlanDTO["stage"];
type StagePlanFor<Name extends StageName> = Extract<StagePlanDTO, { stage: Name }>;
type WorkOutcome = Extract<StagePlanDTO["outcome"], { type: "work" }>;

export type StagePlanOverrides<Name extends StageName> = {
  changes?: WorkOutcome["changes"];
  drift?: StagePlanFor<Name>["drift"];
  actions?: WorkOutcome["actions"];
  snapshot?: StagePlanFor<Name>["snapshot"];
  will_run?: boolean;
  reason?: string | null;
  blocked?: string | null;
};

/** Test-only shorthand for constructing the closed wire outcome. */
export function stagePlan<Name extends StageName>(
  stage: Name,
  overrides: StagePlanOverrides<Name> = {},
): StagePlanFor<Name> {
  const {
    will_run = false,
    reason = null,
    blocked = null,
    changes = [],
    actions = [],
    ...fields
  } = overrides;
  const outcome =
    blocked !== null
      ? ({ type: "blocked", message: blocked } as const)
      : will_run || changes.length > 0 || actions.length > 0
        ? ({ type: "work", reason: reason ?? "changed", changes, actions } as const)
        : ({ type: "idle" } as const);
  return {
    stage,
    outcome,
    changes: [],
    drift: [],
    actions: [],
    snapshot: null,
    ...fields,
  } as unknown as StagePlanFor<Name>;
}

export interface RunSummaryOverrides {
  id?: string;
  kind?: RunKind;
  scope?: "listings" | "workspace";
  listings?: string[];
  phase?: RunPhase;
  seen?: boolean;
  reviewed_run_id?: string | null;
  created_at?: string;
}

export function runSummary(overrides: RunSummaryOverrides = {}): RunSummary {
  return {
    id: "run",
    kind: "plan",
    scope: "listings",
    listings: ["take-a-hike"],
    phase: "queued",
    seen: false,
    reviewed_run_id: null,
    created_at: "2026-09-21T10:00:00Z",
    ...overrides,
  } as RunSummary;
}

export function runDetail(
  overrides: RunSummaryOverrides & { events?: RunEvent[] } = {},
): RunDetail {
  const { events = [], ...summary } = overrides;
  return { ...runSummary(summary), events } as RunDetail;
}
