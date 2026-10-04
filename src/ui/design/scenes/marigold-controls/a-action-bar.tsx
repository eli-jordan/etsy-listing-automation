export const meta = {
  title: "A · Single line",
  viewport: "laptop",
  description: "Two clear brush actions, with settings only while editing.",
};
import { ControlsFrame } from "./_ControlsFrame";
import { InlineToolbar } from "./_Toolbars";
export default function Frame() {
  return <ControlsFrame toolbar={(controls) => <InlineToolbar controls={controls} />} />;
}
