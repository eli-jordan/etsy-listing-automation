export const meta = {
  title: "Archived · C Â· Single brush menu",
  viewport: "laptop",
  description: "A single brush action selector with an explicit Done button.",
};
import { ControlsFrame } from "./_ControlsFrame";
import { MenuToolbar } from "./_Toolbars";
export default function Frame() {
  return <ControlsFrame toolbar={(controls) => <MenuToolbar controls={controls} />} />;
}
