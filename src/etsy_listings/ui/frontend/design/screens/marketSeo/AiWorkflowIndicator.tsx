import { MagnifyingGlass, NotePencil, SkipForward, Sparkle, Warning, X } from "@phosphor-icons/react";
import type { ReactNode } from "react";

export type StepId = "brief" | "market" | "seo";
export type StepState = "pending" | "active" | "done" | "skipped" | "warning" | "failed";
export type WorkflowStep = { id: StepId; state: StepState; detail?: string };

const STEPS: Record<StepId, { name: string; about: string; icon: ReactNode; activeLabel: string }> = {
  brief: {
    name: "Brief",
    about: "Describes the design and the exact words on it. Drafted from the artwork only when the Brief field is empty.",
    icon: <NotePencil weight="bold" />,
    activeLabel: "Drafting brief…",
  },
  market: {
    name: "Market research",
    about: "Turns the brief into three Etsy searches, then scores the comparable listings buyers reward.",
    icon: <MagnifyingGlass weight="bold" />,
    activeLabel: "Researching the market…",
  },
  seo: {
    name: "SEO suggestions",
    about: "Writes title, tag and description lead suggestions, worded after the phrases winning listings use.",
    icon: <Sparkle weight="bold" />,
    activeLabel: "Writing suggestions…",
  },
};

const STATE_WORD: Record<StepState, string> = {
  pending: "Waiting",
  active: "In progress",
  done: "Done",
  skipped: "Skipped",
  warning: "Done, with a warning",
  failed: "Failed",
};

/** One line beside the nodes, so the chain reads without hovering. */
function summary(steps: WorkflowStep[]): { text: string; tone: "busy" | "done" | "failed" } {
  const failed = steps.find((s) => s.state === "failed");
  if (failed) return { text: `${STEPS[failed.id].name} failed`, tone: "failed" };
  const active = steps.find((s) => s.state === "active");
  if (active) return { text: STEPS[active.id].activeLabel, tone: "busy" };
  return { text: "Suggestions ready", tone: "done" };
}

function Badge({ state }: { state: StepState }) {
  if (state === "skipped") return <span className="aiflow__badge aiflow__badge--skipped"><SkipForward weight="fill" /></span>;
  if (state === "warning") return <span className="aiflow__badge aiflow__badge--warning"><Warning weight="fill" /></span>;
  if (state === "failed") return <span className="aiflow__badge aiflow__badge--failed"><X weight="bold" /></span>;
  return null;
}

/**
 * The page head's AI activity: PRD 68's brief, then market research, then the
 * SEO proposal, as three connected nodes. Replaces the "Generating brief…" /
 * "Generating SEO…" spinner line. `openTip` pins one node's hover card open,
 * for the canvas only.
 */
export function AiWorkflowIndicator({ steps, openTip }: { steps: WorkflowStep[]; openTip?: StepId }) {
  const line = summary(steps);
  return (
    <div className="aiflow" role="status" aria-live="polite" aria-label={`AI Mode: ${line.text}`}>
      <ol className="aiflow__nodes">
        {steps.map((step, index) => {
          const meta = STEPS[step.id];
          const tipId = `aiflow-tip-${step.id}`;
          const prev = steps[index - 1];
          const linkDone = prev && (prev.state === "done" || prev.state === "skipped" || prev.state === "warning");
          return (
            <li className="aiflow__step" key={step.id}>
              {index > 0 && <span className={linkDone ? "aiflow__link aiflow__link--done" : "aiflow__link"} aria-hidden="true" />}
              <span
                className={`aiflow__node aiflow__node--${step.state}${openTip === step.id ? " aiflow__node--tip-open" : ""}`}
                tabIndex={0}
                aria-describedby={tipId}
                aria-label={`${meta.name}: ${STATE_WORD[step.state]}`}
              >
                {meta.icon}
                <Badge state={step.state} />
                <span className="aiflow__tip" id={tipId} role="tooltip">
                  <span className="aiflow__tip-head">
                    <strong>{meta.name}</strong>
                    <span className={`aiflow__tip-state aiflow__tip-state--${step.state}`}>{STATE_WORD[step.state]}</span>
                  </span>
                  <span className="aiflow__tip-about">{meta.about}</span>
                  {step.detail && <span className="aiflow__tip-detail">{step.detail}</span>}
                </span>
              </span>
            </li>
          );
        })}
      </ol>
      <span className={`aiflow__label aiflow__label--${line.tone}`}>{line.text}</span>
    </div>
  );
}
