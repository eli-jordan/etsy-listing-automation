import { useEffect } from "react";
import { useBlocker } from "react-router-dom";

/**
 * Warn before navigation would discard values the server has not written
 * (spec, *Completeness and editing*; UI doc §3) -- a listing template's edit
 * that made it incomplete, which template completeness keeps off the disk.
 *
 * Two ways out of the page, two guards. Leaving the app (reload, close, a
 * typed URL) is the browser's own `beforeunload` prompt, which is the only
 * one it allows there. Moving inside the app is React Router's blocker, and
 * the caller shows the question: this answers `null` while nothing is
 * blocked, or the two ways to answer it.
 *
 * A `replace` navigation is never blocked. That is the editor moving itself
 * -- naming a template swaps `/new` for `/:name` -- and it happens in the
 * same tick as the save that made the state safe, before this hook has seen
 * the new state.
 */
export function useUnsavedWarning(
  active: boolean,
): { proceed: () => void; stay: () => void } | null {
  const blocker = useBlocker(
    ({ currentLocation, nextLocation, historyAction }) =>
      active && historyAction !== "REPLACE" && currentLocation.pathname !== nextLocation.pathname,
  );

  useEffect(() => {
    if (!active) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Chrome still wants the legacy property set to show the prompt.
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [active]);

  if (blocker.state !== "blocked") return null;
  return { proceed: () => blocker.proceed(), stay: () => blocker.reset() };
}
