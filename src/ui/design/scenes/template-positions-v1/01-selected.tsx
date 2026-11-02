import { EditorFrame } from "./_EditorFrame";
import { tuned } from "./_fixtures";
import { ViewPane } from "./_panes";

export const meta = {
  title: "1 · Entry with a custom position · v1",
  viewport: "laptop",
  description: "Images tab with a cc1717-folded entry selected: the chip says this listing positions the design; Adjust position opens Position mode.",
};

export default function Frame() {
  return <EditorFrame pane={<ViewPane pose={tuned} />} />;
}
