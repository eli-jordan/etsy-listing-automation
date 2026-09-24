import type { AiSeoMode } from "./useAiSeoMode";
import type { AutoDesignBrief } from "./useAutoDesignBrief";

/**
 * What the editor's page head says while PRD 68's chain runs, beside the
 * autosave meta line.
 *
 * It belongs next to "Saved a moment ago" rather than beside the field it is
 * about, because it reports the same *kind* of thing that line does: work
 * this editor started on its own and will finish without being asked. A
 * seller who attached a design is normally looking at Variants, several
 * scrolls from the Brief field, and the head is the one part of the editor
 * that reads the same on every tab.
 *
 * Two messages, in the order the chain produces them, and nothing else --
 * no cancel, no retry, no count. The failure a draft can end in is reported
 * where it can be acted on (the Brief field is simply still empty, and AI
 * Mode's own control explains what it needs); a spinner in a page head is
 * the wrong place to put a decision.
 *
 * Renders nothing at all in the ordinary case, which is most of the time.
 */
export function AiActivityIndicator({ auto, aiSeo }: { auto: AutoDesignBrief; aiSeo: AiSeoMode }) {
  const label =
    auto.phase === "drafting"
      ? "Generating brief…"
      : aiSeo.phase === "loading"
        ? "Generating SEO…"
        : null;
  if (label === null) return null;

  return (
    <span className="ai-activity" role="status" aria-live="polite">
      {/* The app's one spinner, the Deploy page's. A second one here, gated
          on `prefers-reduced-motion`, sat perfectly still on a Windows
          machine with "Show animations" off -- which reads as a hang, not as
          work in progress. A loading spinner is the case where the motion
          *is* the information. */}
      <span className="dv-spinner" aria-hidden="true" />
      {label}
    </span>
  );
}
