import type { AiSeoMode } from "./useAiSeoMode";
import type { AutoDesignBrief } from "./useAutoDesignBrief";

/**
 * What the design strip says while PRD 68's chain runs, for a seller who is
 * usually looking at **Variants** when it starts.
 *
 * It sits directly under `DesignSelect` because that is where the action
 * that started it was: attaching a design quietly costs a minute of a
 * metered CLI, and a seller who cannot see that happening has no way to know
 * why their Brief field fills in by itself a moment later, or why AI Mode is
 * briefly disabled.
 *
 * One line, never a banner, never a modal, and never a control that blocks
 * anything -- the whole point of the chain is that the seller keeps working
 * (`docs/ui-listing-seo-interactions.md` section 2: "The seller may continue
 * editing other fields while generation runs"). The only action offered is
 * the one that is useful at each moment: go and look.
 *
 * Renders nothing at all in the ordinary case, which is most of the time.
 */
export function AutoDesignBriefStatus({
  auto,
  aiSeo,
  onOpenDetails,
}: {
  auto: AutoDesignBrief;
  aiSeo: AiSeoMode;
  onOpenDetails: () => void;
}) {
  // Generation reached from the chain, not from the seller pressing AI Mode
  // on the Details tab -- the tab's own control already reports that case,
  // with a timer and a Cancel, and saying it twice on one screen would read
  // as two things happening.
  const generating = aiSeo.phase === "loading";
  const suggestionsReady = aiSeo.proposal !== null && !aiSeo.stale;

  if (auto.waiting) {
    return (
      <Line>
        <span>Save this listing to draft a brief from your design.</span>
      </Line>
    );
  }

  if (auto.phase === "drafting") {
    return (
      <Line busy>
        <span>Reading your design to draft a brief…</span>
      </Line>
    );
  }

  if (auto.phase === "failed") {
    return (
      <Line>
        <span>Couldn’t draft a brief from this design. Write one in Listing Details.</span>
        <button type="button" onClick={onOpenDetails}>
          Open Listing Details
        </button>
      </Line>
    );
  }

  if (generating) {
    return (
      <Line busy>
        <span>Drafting SEO suggestions from your brief…</span>
      </Line>
    );
  }

  if (suggestionsReady) {
    return (
      <Line>
        <span>SEO suggestions are ready for review.</span>
        <button type="button" onClick={onOpenDetails}>
          Open Listing Details
        </button>
      </Line>
    );
  }

  return null;
}

/** `role="status"` with `aria-live="polite"`, once, around whichever message
 * is current -- section 10 asks for "concise polite live-region messages"
 * and specifically not one announcement per item. */
function Line({ children, busy = false }: { children: React.ReactNode; busy?: boolean }) {
  return (
    <div
      className={busy ? "auto-brief-status auto-brief-status--busy" : "auto-brief-status"}
      role="status"
      aria-live="polite"
    >
      {children}
    </div>
  );
}
