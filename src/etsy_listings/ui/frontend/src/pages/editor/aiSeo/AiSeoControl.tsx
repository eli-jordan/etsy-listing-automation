import type { Ref } from "react";
import type { AiSeoMode } from "./useAiSeoMode";

/** The sparkle **AI Mode** control and its inline loading/failure status
 * (`docs/ui-listing-seo-interactions.md` sections 1-2). Renders nothing at
 * all when `mode.available` is `false` -- the settled "Entry point"
 * decision is hidden, not disabled, so there is no tooltip-bearing button to
 * explain here.
 *
 * The same click handler starts the first request and regenerates a stale
 * one (`useAiSeoMode.generate`'s own docstring): the v3 mockup's "not
 * disabled while stale" button is the one place this control's behaviour
 * changes by state, so there is no separate "Regenerate" button to build. */
export function AiSeoControl({
  mode,
  buttonRef,
}: {
  mode: AiSeoMode;
  buttonRef?: Ref<HTMLButtonElement>;
}) {
  if (!mode.available) return null;

  return (
    <div className="seo-ai-mode-wrap">
      <button
        ref={buttonRef}
        className="btn btn-secondary seo-ai-mode"
        type="button"
        disabled={mode.phase === "loading"}
        onClick={mode.generate}
      >
        <SparkleIcon /> AI Mode
      </button>

      {mode.phase === "loading" && (
        <div className="seo-inline-status" role="status" aria-live="polite">
          <span className="seo-inline-status__pulse" aria-hidden="true" />
          <span>Generating title, tag, and description suggestions…</span>
          <button type="button" onClick={mode.cancel}>
            Cancel
          </button>
        </div>
      )}

      {mode.phase === "failed" && (
        <div className="seo-inline-status" role="status" aria-live="polite">
          <span>AI Mode couldn’t generate valid suggestions. Nothing changed.</span>
          <button type="button" onClick={mode.generate}>
            Try again
          </button>
        </div>
      )}
    </div>
  );
}

function SparkleIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20" width="14" height="14">
      <path d="M8.2 2.2c.5 3.1 1.5 4.1 4.6 4.6-3.1.5-4.1 1.5-4.6 4.6-.5-3.1-1.5-4.1-4.6-4.6 3.1-.5 4.1-1.5 4.6-4.6Z" />
      <path d="M14.5 11.2c.3 2 1 2.7 3 3-2 .3-2.7 1-3 3-.3-2-1-2.7-3-3 2-.3 2.7-1 3-3Z" />
    </svg>
  );
}
