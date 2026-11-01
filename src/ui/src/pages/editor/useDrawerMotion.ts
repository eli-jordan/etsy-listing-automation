import { useState } from "react";

/** Whether the AI SEO drawers slide in: only when a request that was loading
 * has just landed a proposal on a visible tab, and only until that proposal
 * is resolved. Tracked during render, from the phase it last saw, so the
 * drawers never paint a frame without the motion they open with. */
export function useDrawerMotion(phase: string | null, hasProposal: boolean): boolean {
  const [trackedPhase, setTrackedPhase] = useState(phase);
  const [drawerMotion, setDrawerMotion] = useState(false);
  if (phase !== trackedPhase) {
    setTrackedPhase(phase);
    if (trackedPhase === "loading") {
      setDrawerMotion(hasProposal && document.visibilityState === "visible");
    }
  }
  if (!hasProposal && drawerMotion) setDrawerMotion(false);
  return drawerMotion;
}
