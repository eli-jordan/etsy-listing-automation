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
      <Spinner />
      {label}
    </span>
  );
}

/** A ring with one lit quarter, rotated by CSS. An SVG rather than a
 * character or a border trick so it keeps its size next to the meta line's
 * 11px text, and `aria-hidden` because the label beside it already says what
 * it means. Motion is suppressed under `prefers-reduced-motion` in the
 * stylesheet, where the label alone still reports the state. */
function Spinner() {
  return (
    <svg
      className="ai-activity__spinner"
      aria-hidden="true"
      viewBox="0 0 16 16"
      width="11"
      height="11"
    >
      <circle
        cx="8"
        cy="8"
        r="6"
        fill="none"
        strokeWidth="2.5"
        opacity="0.25"
        stroke="currentColor"
      />
      <path
        d="M8 2a6 6 0 0 1 6 6"
        fill="none"
        strokeWidth="2.5"
        strokeLinecap="round"
        stroke="currentColor"
      />
    </svg>
  );
}
