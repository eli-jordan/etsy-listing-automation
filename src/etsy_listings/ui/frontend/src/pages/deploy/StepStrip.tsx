import { useEffect, useState } from "react";
import type { StageRuntimeStatus } from "./deployState";
import type { PlanDTO, StagePlanDTO } from "../../types";
import { STAGE_LABELS, stageActions, stageBlocked, stageReason, stageWillRun } from "../../types";

/**
 * "What apply will do" / "What apply did" -- one cell per stage the plan
 * actually returned, in pipeline order (spec's "Step strip" element,
 * decision 11: nothing here hard-codes five stages, so a `retract`-only
 * plan draws one cell and an `_all_blocked` listing draws every stage red).
 *
 * A stage the engine puts under another by `group` (`etsy_videos` under
 * `etsy_media`, PRD 71) is drawn beside it inside one labelled group, so the
 * strip reads as the CLI's `etsy_media/etsy_videos` does. The grouping is the
 * engine's data, never inferred here from a name.
 */

type CellState =
  "run" | "skip" | "blocked" | "running" | "applying-log" | "done" | "failed" | "not-reached";

function cellState(
  stagePlan: StagePlanDTO,
  runtime: StageRuntimeStatus | undefined,
  failedEarlier: boolean,
): CellState {
  if (runtime?.kind === "applying") return "running";
  if (runtime?.kind === "applied") return "done";
  if (runtime?.kind === "failed") return "failed";
  if (stageWillRun(stagePlan) && failedEarlier) return "not-reached";
  if (stageBlocked(stagePlan) !== null) return "blocked";
  return stageWillRun(stagePlan) ? "run" : "skip";
}

function Icon({ state }: { state: CellState }) {
  if (state === "running") return <span className="dv-spinner" aria-hidden="true" />;
  if (state === "run") {
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="6.5" fill="var(--color-accent)" />
        <path d="M6.5 5.2 10.5 8l-4 2.8Z" fill="var(--color-bg)" />
      </svg>
    );
  }
  if (state === "blocked" || state === "failed") {
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="6.5" fill="var(--color-danger)" />
        <path d="M5 11 11 5" stroke="var(--color-bg)" strokeWidth="1.8" />
      </svg>
    );
  }
  if (state === "done") {
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="6.5" fill="var(--color-accent-2)" />
        <path
          d="m5 8.2 2 2 4-4.2"
          stroke="var(--color-bg)"
          strokeWidth="1.8"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8" r="5.5" fill="none" stroke="var(--color-neutral-400)" strokeWidth="2" />
    </svg>
  );
}

function whyText(
  state: CellState,
  stagePlan: StagePlanDTO,
  runtime: StageRuntimeStatus | undefined,
): string {
  switch (state) {
    case "blocked":
      return "Blocked";
    case "skip":
      return "No changes";
    case "done":
      return "Done";
    case "running":
      return "Running";
    case "failed":
      return (runtime && runtime.kind === "failed" && runtime.message) || "Failed";
    case "not-reached":
      return "Not reached";
    default:
      return stageReason(stagePlan) ?? "";
  }
}

function formatElapsed(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes}:${seconds.toString().padStart(2, "0")}` : `${seconds}s`;
}

function StageTimer({ runtime }: { runtime: StageRuntimeStatus }) {
  const [now, setNow] = useState(Date.now);

  useEffect(() => {
    if (runtime.kind !== "applying") return;
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [runtime.kind, runtime.startedAt]);

  const end = runtime.kind === "applying" ? now : runtime.finishedAt;
  return (
    <span
      className="dv-step__timer"
      aria-label={`Elapsed ${formatElapsed(end - runtime.startedAt)}`}
    >
      {formatElapsed(end - runtime.startedAt)}
    </span>
  );
}

function StepCell({
  stagePlan,
  runtime,
  failedEarlier,
}: {
  stagePlan: StagePlanDTO;
  runtime: StageRuntimeStatus | undefined;
  failedEarlier: boolean;
}) {
  const [open, setOpen] = useState(false);
  const state = cellState(stagePlan, runtime, failedEarlier);
  const label = STAGE_LABELS[stagePlan.stage] ?? stagePlan.stage;
  const log = runtime?.kind === "applying" ? runtime.log : null;
  const actions = stageActions(stagePlan);

  return (
    <div className={`dv-step dv-step--${state}`}>
      <div className="dv-step__top">
        <Icon state={state} />
        <span className="dv-step__name">{label}</span>
        {runtime && <StageTimer runtime={runtime} />}
      </div>
      <div className={state === "running" ? "dv-step__why" : "dv-step__why"}>
        {whyText(state, stagePlan, runtime)}
      </div>
      {log !== null && <div className="dv-step__log">&rsaquo; {log}</div>}
      {(state === "run" || state === "done") && actions.length > 0 && (
        <details open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
          <summary>
            {actions.length} action{actions.length > 1 ? "s" : ""}
          </summary>
          <ul>
            {actions.map((action, index) => (
              <li key={index}>
                {action.description}
                {action.outputs.length > 0 && (
                  <>
                    {" → "}
                    <span className="dv-mono">{action.outputs[0]?.split("/").pop()}</span>
                  </>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/** The strip's cells, each stage with the ones grouped under it. A stage
 * whose group is not in the plan stands on its own. */
function nest(stagePlans: readonly StagePlanDTO[]): StagePlanDTO[][] {
  const present = new Set(stagePlans.map((s) => s.stage as string));
  const rows: StagePlanDTO[][] = [];
  for (const stagePlan of stagePlans) {
    const parent = stagePlan.group ?? null;
    const row =
      parent !== null && present.has(parent) ? rows.find((r) => r[0]?.stage === parent) : undefined;
    if (row !== undefined) row.push(stagePlan);
    else rows.push([stagePlan]);
  }
  return rows;
}

export function StepStrip({
  plan,
  stageRuntime,
  heading,
}: {
  plan: PlanDTO;
  stageRuntime: Record<string, StageRuntimeStatus>;
  heading: string;
}) {
  const failedIndex = plan.stage_plans.findIndex((s) => stageRuntime[s.stage]?.kind === "failed");
  const cell = (stagePlan: StagePlanDTO) => (
    <StepCell
      key={stagePlan.stage}
      stagePlan={stagePlan}
      runtime={stageRuntime[stagePlan.stage]}
      failedEarlier={failedIndex !== -1 && plan.stage_plans.indexOf(stagePlan) > failedIndex}
    />
  );

  return (
    <div className="dv-stack" style={{ gap: 8 }}>
      <span className="dv-eyebrow">{heading}</span>
      <div className="dv-steps">
        {nest(plan.stage_plans).map((row) => {
          const head = row[0] as StagePlanDTO;
          if (row.length === 1) return cell(head);
          const label = STAGE_LABELS[head.stage] ?? head.stage;
          return (
            <div
              key={head.stage}
              className="dv-step-group"
              role="group"
              aria-label={label}
              style={{
                gridColumn: `span ${row.length}`,
                gridTemplateColumns: `repeat(${row.length}, minmax(0, 1fr))`,
              }}
            >
              {row.map(cell)}
            </div>
          );
        })}
      </div>
    </div>
  );
}
