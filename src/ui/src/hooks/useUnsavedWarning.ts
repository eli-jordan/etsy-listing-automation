import { useEffect } from "react";
import { useBlocker } from "react-router-dom";

/**
 * Values the server has not written (batch-creation spec, *Completeness and editing*).
 * Leaving the app gets the browser's `beforeunload` prompt, the only one it allows.
 *
 * A `replace` navigation is never blocked: naming a template swaps `/new` for `/:name`
 * in the same tick as the save that made the state safe, before this hook sees it.
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
