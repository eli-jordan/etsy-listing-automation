import { EditorFrame } from "../_EditorFrame";
import { tuned } from "../_fixtures";
import { BarPane } from "../_panes";

export const meta = {
  title: "2A · Position mode — foot bar · v1",
  viewport: "laptop",
  description: "Direction A: handles on the stage, and the preview foot turns into a bar with size, offset and tilt against their limits.",
};

export default function Frame() {
  return <EditorFrame pane={<BarPane initial={tuned} />} />;
}
