export const meta = {
  title: "C \u00b7 Settings dialog with reference card",
  viewport: "laptop",
  description:
    "Custom Marigold inference controls; prototype defaults and linked information cards.",
};
import { InferenceFrame } from "./_Frame";
export default function Frame() {
  return <InferenceFrame variant="dialog" />;
}
