import { EditorFrame } from "./_EditorFrame";
import { atLimit } from "./_fixtures";
import { PositionPane } from "./_panes";

export const meta = {
  title: "3 · Dragged to the size limit · v2",
  viewport: "laptop",
  description: "The corner handle stopped at the largest size: handles turn amber and the note line says why it won't grow further.",
};

export default function Frame() {
  return <EditorFrame pane={<PositionPane initial={atLimit} editing />} />;
}
