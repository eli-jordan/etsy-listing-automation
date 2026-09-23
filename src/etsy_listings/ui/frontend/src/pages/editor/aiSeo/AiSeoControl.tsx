import { useEffect, useState, type Ref } from "react";
import type { AiSeoMode } from "./useAiSeoMode";

/** The sparkle **AI Mode** control and its hover card.
 * It remains visible while prerequisites are missing, but cannot start a request.
 * While a request runs, the button glows. The timer and Cancel sit under the
 * brief, aligned to its right edge, and the generating card appears only
 * while the button is hovered.
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
  const loading = mode.phase === "loading";
  const elapsed = useElapsed(loading);
  return (
    <>
      <div
        className="seo-ai-mode-anchor"
        tabIndex={!mode.available ? 0 : undefined}
        role="group"
        aria-label="AI Mode requirements"
        aria-describedby="seo-ai-mode-tip"
      >
        <button
          ref={buttonRef}
          className={
            loading
              ? "btn btn-secondary seo-ai-mode seo-ai-mode--busy"
              : "btn btn-secondary seo-ai-mode"
          }
          type="button"
          disabled={!mode.available || loading}
          onClick={mode.generate}
          aria-describedby="seo-ai-mode-tip"
        >
          <SparkleIcon /> AI Mode
        </button>

        <div id="seo-ai-mode-tip" className="seo-ai-mode-tip" role="tooltip">
          {loading ? (
            <p className="seo-ai-mode-tip__note">
              Generating title, description and tag recommendations for your review
            </p>
          ) : mode.available ? (
            <p className="seo-ai-mode-tip__note">
              Generates SEO fields using AI (title, description lead and tags)
            </p>
          ) : (
            <>
              <strong>Ready to use AI Mode?</strong>
              <ul>
                {mode.requirements.map((requirement) => (
                  <li
                    key={requirement.label}
                    className={requirement.ready ? "is-ready" : "is-missing"}
                  >
                    {requirement.label}
                  </li>
                ))}
              </ul>
              {mode.reason && <p>{mode.reason}</p>}
            </>
          )}
        </div>
      </div>

      {loading && (
        <div className="seo-ai-mode-progress">
          <span className="seo-ai-mode-elapsed">
            Generating for {formatElapsed(elapsed)} seconds
          </span>
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
    </>
  );
}

/** Seconds since `active` became true, reset when it stops. */
function useElapsed(active: boolean): number {
  const [seconds, setSeconds] = useState(0);
  const [prevActive, setPrevActive] = useState(active);
  if (active !== prevActive) {
    setPrevActive(active);
    if (!active) setSeconds(0);
  }
  useEffect(() => {
    if (!active) return;
    const started = Date.now();
    const update = () => setSeconds(Math.floor((Date.now() - started) / 1000));
    const id = window.setInterval(update, 250);
    return () => window.clearInterval(id);
  }, [active]);
  return active ? seconds : 0;
}

function formatElapsed(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
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
