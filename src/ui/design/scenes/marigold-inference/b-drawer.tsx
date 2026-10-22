export const meta = {
  title: "B \u00b7 Preparation settings drawer",
  viewport: "laptop",
  description:
    "Custom Marigold inference controls; prototype defaults and linked information cards.",
};
import { InferenceFrame } from "./_Frame";
export default function Frame() {
  return <InferenceFrame variant="drawer" />;
}
