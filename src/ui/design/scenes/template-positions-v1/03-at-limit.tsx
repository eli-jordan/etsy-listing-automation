import { EditorFrame } from "./_EditorFrame";
import { atLimit } from "./_fixtures";
import { BarPane } from "./_panes";

export const meta = {
  title: "3 · Dragged to the size limit · v1",
  viewport: "laptop",
  description: "The corner handle stopped at 110%: Size reads 'at limit' in words and the meter turns amber. Shown in direction A.",
};

export default function Frame() {
  return <EditorFrame pane={<BarPane initial={atLimit} />} />;
}
