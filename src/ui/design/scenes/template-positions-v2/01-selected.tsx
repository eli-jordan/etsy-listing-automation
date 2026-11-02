import { EditorFrame } from "./_EditorFrame";
import { tuned } from "./_fixtures";
import { PositionPane } from "./_panes";

export const meta = {
  title: "1 · Entry with a custom position · v2",
  viewport: "laptop",
  description: "Images tab with a cc1717-folded entry selected: the chip shows this listing's position; the Adjust position switch turns the handles on.",
};

export default function Frame() {
  return <EditorFrame pane={<PositionPane initial={tuned} />} />;
}
