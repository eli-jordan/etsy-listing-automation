import { EditorFrame } from "./_EditorFrame";
import { tuned } from "./_fixtures";
import { PositionPane } from "./_panes";

export const meta = {
  title: "2 · Adjusting the position",
  viewport: "laptop",
  description: "Switch on: drag to move, a corner to resize, the top handle to tilt; handles stop at the limits. Reset to template removes the listing's position.",
};

export default function Frame() {
  return <EditorFrame pane={<PositionPane initial={tuned} editing switchGoto="template-positions/01-selected" />} />;
}
