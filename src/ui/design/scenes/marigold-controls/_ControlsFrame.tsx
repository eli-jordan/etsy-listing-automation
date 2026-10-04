import { MarigoldScreen, type MaskControls } from "../marigold-v3/_MarigoldScreen";
import type { ReactNode } from "react";
import "./_controls.css";
export function ControlsFrame({ toolbar }: { toolbar: (controls: MaskControls) => ReactNode }) {
  return (
    <div className="mc-frame">
      <MarigoldScreen
        state="edit"
        initialTool="exclude"
        toolbar={toolbar}
        maskPresentation="print-area"
      />
    </div>
  );
}
