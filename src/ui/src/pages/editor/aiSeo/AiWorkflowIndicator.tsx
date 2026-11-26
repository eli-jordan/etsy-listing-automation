import { MagnifyingGlassIcon } from "@phosphor-icons/react/dist/csr/MagnifyingGlass";
import { NotePencilIcon } from "@phosphor-icons/react/dist/csr/NotePencil";
import { SkipForwardIcon } from "@phosphor-icons/react/dist/csr/SkipForward";
import { SparkleIcon } from "@phosphor-icons/react/dist/csr/Sparkle";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { type ReactNode, useEffect, useId, useState } from "react";
import type { WorkflowStep } from "../../../types";

type StepId = WorkflowStep["id"];
type StepState = WorkflowStep["state"];

const STEPS: Record<StepId, { name: string; about: string; icon: ReactNode; activeLabel: string }> =
  {
    brief: {
      name: "Brief",
      about:
        "Describes the design and the exact words on it. Drafted from the artwork only when the Brief field is empty.",
      icon: <NotePencilIcon weight="bold" />,
      activeLabel: "Drafting brief…",
    },
    market: {
      name: "Market research",
      about:
        "Turns the brief into three Etsy searches, then scores the comparable listings buyers reward.",
      icon: <MagnifyingGlassIcon weight="bold" />,
      activeLabel: "Researching the market…",
    },
    seo: {
      name: "SEO suggestions",
      about:
        "Writes title, tag and description lead suggestions, worded after the phrases winning listings use.",
      icon: <SparkleIcon weight="bold" />,
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

type Tone = "busy" | "done" | "failed";

function summary(steps: WorkflowStep[]): { text: string; tone: Tone } | null {
  const failed = steps.find((s) => s.state === "failed");
  if (failed) return { text: `${STEPS[failed.id].name} failed`, tone: "failed" };
  const active = steps.find((s) => s.state === "active");
  if (active) return { text: STEPS[active.id].activeLabel, tone: "busy" };
  if (steps.length > 0 && steps.every((s) => connectorSolid(s.state))) {
    const briefOnly = steps.find((s) => s.id === "seo")?.state === "skipped";
    return { text: briefOnly ? "Brief ready" : "Suggestions ready", tone: "done" };
  }
  return null;
}

const READY_FOR_MS = 4000;
const FADE_MS = 300;

function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

function connectorSolid(state: StepState): boolean {
  return state === "done" || state === "skipped" || state === "warning";
}

function Badge({ state }: { state: StepState }) {
  if (state === "skipped")
    return (
      <span className="aiflow__badge aiflow__badge--skipped">
        <SkipForwardIcon weight="fill" />
      </span>
    );
  if (state === "warning")
    return (
      <span className="aiflow__badge aiflow__badge--warning">
        <WarningIcon weight="fill" />
      </span>
    );
  if (state === "failed")
    return (
      <span className="aiflow__badge aiflow__badge--failed">
        <XIcon weight="bold" />
      </span>
    );
  return null;
}

export function AiWorkflowIndicator({
  steps,
  running,
}: {
  steps: WorkflowStep[];
  running: boolean;
}) {
  const idBase = useId();
  const line = summary(steps);
  const finished =
    steps.length > 0 && steps.every((s) => s.state === "done" || s.state === "skipped");

  // Both adjusted while rendering, not in an effect, so a new run never
  // paints a frame with the last run's faded state.
  const [watched, setWatched] = useState(running);
  const nowWatched = steps.length === 0 ? running : watched || running;
  if (nowWatched !== watched) setWatched(nowWatched);
  const [fade, setFade] = useState<"shown" | "fading" | "gone">("shown");
  if (!finished && fade !== "shown") setFade("shown");

  useEffect(() => {
    if (!finished || !nowWatched) return;
    let fadeTimer: ReturnType<typeof setTimeout> | undefined;
    const readyTimer = setTimeout(() => {
      if (prefersReducedMotion()) return setFade("gone");
      setFade("fading");
      fadeTimer = setTimeout(() => setFade("gone"), FADE_MS);
    }, READY_FOR_MS);
    return () => {
      clearTimeout(readyTimer);
      clearTimeout(fadeTimer);
    };
  }, [finished, nowWatched]);

  if (line === null) return null;
  if (finished && (!nowWatched || fade === "gone")) return null;

  return (
    <div
      className={fade === "fading" ? "aiflow aiflow--fading" : "aiflow"}
      role="status"
      aria-live="polite"
      aria-label={`AI Mode: ${line.text}`}
    >
      <ol className="aiflow__nodes">
        {steps.map((step, index) => {
          const meta = STEPS[step.id];
          const tipId = `${idBase}-${step.id}`;
          const prev = index > 0 ? steps[index - 1] : undefined;
          return (
            <li className="aiflow__step" key={step.id}>
              {prev !== undefined && (
                <span
                  className={
                    connectorSolid(prev.state) ? "aiflow__link aiflow__link--done" : "aiflow__link"
                  }
                  aria-hidden="true"
                />
              )}
              <span
                className={`aiflow__node aiflow__node--${step.state}`}
                tabIndex={0}
                aria-describedby={tipId}
                aria-label={`${meta.name}: ${STATE_WORD[step.state]}`}
              >
                {meta.icon}
                <Badge state={step.state} />
                <span className="aiflow__tip" id={tipId} role="tooltip">
                  <span className="aiflow__tip-head">
                    <strong>{meta.name}</strong>
                    <span className={`aiflow__tip-state aiflow__tip-state--${step.state}`}>
                      {STATE_WORD[step.state]}
                    </span>
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
