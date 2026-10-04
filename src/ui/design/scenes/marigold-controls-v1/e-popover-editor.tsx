export const meta = {
  title: "Archived · E Â· Popover editor",
  viewport: "laptop",
  description: "A quiet Print area strip opens a compact popover for occasional corrections.",
};
import { ControlsFrame } from "./_ControlsFrame";
import { PopoverToolbar } from "./_Toolbars";
export default function Frame() {
  return <ControlsFrame toolbar={(controls) => <PopoverToolbar controls={controls} />} />;
}
