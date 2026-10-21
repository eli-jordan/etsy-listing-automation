export const meta = {
  title: "D · Floating dock",
  viewport: "laptop",
  description: "Larger Hide print and Bring print back actions explain the two brushes.",
};
import { ControlsFrame } from "./_ControlsFrame";
import { ActionToolbar } from "./_Toolbars";
export default function Frame() {
  return <ControlsFrame toolbar={(controls) => <ActionToolbar controls={controls} />} />;
}
