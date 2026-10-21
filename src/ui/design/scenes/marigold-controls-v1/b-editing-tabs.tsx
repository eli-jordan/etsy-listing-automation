export const meta = {
  title: "Archived · B · Separate editing modes",
  viewport: "laptop",
  description: "Placement and Print area tabs separate moving the design from painting the mask.",
};
import { ControlsFrame } from "./_ControlsFrame";
import { TabbedToolbar } from "./_Toolbars";
export default function Frame() {
  return <ControlsFrame toolbar={(controls) => <TabbedToolbar controls={controls} />} />;
}
