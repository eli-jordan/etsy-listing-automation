import { EditorFrame } from "../_EditorFrame";
import { tuned } from "../_fixtures";
import { InspectorPane } from "../_panes";

export const meta = {
  title: "2B · Position mode — stage inspector · v1",
  viewport: "laptop",
  description: "Direction B: handles on the stage plus a small inspector card pinned to its corner; the foot keeps the title and scope note.",
};

export default function Frame() {
  return <EditorFrame pane={<InspectorPane initial={tuned} />} />;
}
