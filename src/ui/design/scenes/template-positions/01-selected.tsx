import { EditorFrame } from "./_EditorFrame";
import { tuned } from "./_fixtures";
import { PositionPane } from "./_panes";

export const meta = {
  title: "1 · Entry selected",
  viewport: "laptop",
  description: "Prototype start: a cc1717-folded entry previews at this listing's position. Flip Adjust position to edit; click the colour-pair tile for a multiple template.",
};

export default function Frame() {
  return <EditorFrame pane={<PositionPane initial={tuned} switchGoto="template-positions/02-adjusting" />} />;
}
