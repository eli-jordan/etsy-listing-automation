import type { Ref } from "react";
import type { AiSeoMode } from "./useAiSeoMode";

/** The sparkle **AI Mode** control and its inline loading/failure status.
 * It remains visible while prerequisites are missing, but cannot start a request.
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
  return (
    <div
      className="seo-ai-mode-wrap"
      tabIndex={!mode.available ? 0 : undefined}
      role="group"
      aria-label="AI Mode requirements"
      aria-describedby="seo-ai-mode-tip"
    >
      <button
        ref={buttonRef}
        className="btn btn-secondary seo-ai-mode"
        type="button"
        disabled={!mode.available || mode.phase === "loading"}
        onClick={mode.generate}
        aria-describedby="seo-ai-mode-tip"
      >
        <SparkleIcon /> AI Mode
      </button>

      <div id="seo-ai-mode-tip" className="seo-ai-mode-tip" role="tooltip">
        <strong>Ready to use AI Mode?</strong>
        <ul>
          {mode.requirements.map((requirement) => (
            <li key={requirement.label} className={requirement.ready ? "is-ready" : "is-missing"}>
              {requirement.label}
            </li>
          ))}
        </ul>
        {mode.reason && <p>{mode.reason}</p>}
      </div>

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
      <path
        className="seo-sparkle-primary"
        d="M8.2 2.2c.5 3.1 1.5 4.1 4.6 4.6-3.1.5-4.1 1.5-4.6 4.6-.5-3.1-1.5-4.1-4.6-4.6 3.1-.5 4.1-1.5 4.6-4.6Z"
      />
      <path
        className="seo-sparkle-secondary"
        d="M14.5 11.2c.3 2 1 2.7 3 3-2 .3-2.7 1-3 3-.3-2-1-2.7-3-3 2-.3 2.7-1 3-3Z"
      />
    </svg>
  );
}
