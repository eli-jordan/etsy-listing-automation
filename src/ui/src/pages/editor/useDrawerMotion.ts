import { useState } from "react";

/** Set during render: an effect would paint one frame of the drawers without their motion. */
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
