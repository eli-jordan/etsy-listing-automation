import type { WorkflowStep } from "../../../types";

/** What each node says while it is the active one -- the labels of
 * `docs/ui-market-seo-interactions.md` section 1's anatomy table. */
const ACTIVE_LABEL: Record<WorkflowStep["id"], string> = {
  brief: "Drafting brief…",
  market: "Researching the market…",
  seo: "Writing suggestions…",
};

/**
 * What the editor's page head says while an AI run works, beside the
 * autosave meta line: the label of the step that is running, taken from the
 * run's latest `step` events (market-seo.md, *AI runs*), so a reload mid-run
 * shows it again.
 *
 * It belongs next to "Saved a moment ago" rather than beside the field it is
 * about, because it reports the same *kind* of thing that line does: work
 * this editor started and will finish without being asked. A seller who
 * attached a design is normally looking at Variants, several scrolls from
 * the Brief field, and the head is the one part of the editor that reads the
 * same on every tab.
 *
 * Renders nothing at all when no step is running, which is most of the time.
 * PR 7 replaces this with the three-node workflow indicator.
 */
export function AiActivityIndicator({ steps }: { steps: WorkflowStep[] }) {
  const active = steps.find((step) => step.state === "active");
  if (active === undefined) return null;

  return (
    <span className="ai-activity" role="status" aria-live="polite">
      {/* The app's one spinner, the Deploy page's. A second one here, gated
          on `prefers-reduced-motion`, sat perfectly still on a Windows
          machine with "Show animations" off -- which reads as a hang, not as
          work in progress. A loading spinner is the case where the motion
          *is* the information. */}
      <span className="dv-spinner" aria-hidden="true" />
      {ACTIVE_LABEL[active.id]}
    </span>
  );
}
