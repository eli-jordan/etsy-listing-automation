import { EditorFrame } from "./_EditorFrame";
import { tuned } from "./_fixtures";
import { PositionPane } from "./_panes";

export const meta = {
  title: "2 · Adjusting the position · v2",
  viewport: "laptop",
  description: "Switch on: drag to move, a corner to resize, the top handle to tilt. The chip tracks the drag; the dashed box is the template's own.",
};

export default function Frame() {
  return <EditorFrame pane={<PositionPane initial={tuned} editing />} />;
}
