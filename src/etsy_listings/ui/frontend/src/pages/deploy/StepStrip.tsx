import { useEffect, useState } from "react";
import type { StageRuntimeStatus } from "./deployState";
import type { PlanDTO, StagePlanDTO } from "../../types";
import { STAGE_LABELS } from "../../types";

/**
 * "What apply will do" / "What apply did" -- one cell per stage the plan
 * actually returned, in pipeline order (spec's "Step strip" element,
 * decision 11: nothing here hard-codes five stages, so a `retract`-only
 * plan draws one cell and an `_all_blocked` listing draws every stage red).
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
  if (stagePlan.will_run && failedEarlier) return "not-reached";
  if (stagePlan.blocked !== null) return "blocked";
  return stagePlan.will_run ? "run" : "skip";
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
      return stagePlan.reason ?? "";
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
  const actions = stagePlan.actions;

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

  return (
    <div className="dv-stack" style={{ gap: 8 }}>
      <span className="dv-eyebrow">{heading}</span>
      <div className="dv-steps">
        {plan.stage_plans.map((stagePlan, index) => (
          <StepCell
            key={stagePlan.stage}
            stagePlan={stagePlan}
            runtime={stageRuntime[stagePlan.stage]}
            failedEarlier={failedIndex !== -1 && index > failedIndex}
          />
        ))}
      </div>
    </div>
  );
}
