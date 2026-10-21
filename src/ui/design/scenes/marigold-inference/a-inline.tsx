export const meta = {
  title: "A \u00b7 Inline advanced panel",
  viewport: "laptop",
  description:
    "Custom Marigold inference controls; prototype defaults and linked information cards.",
};
import { InferenceFrame } from "./_Frame";
export default function Frame() {
  return <InferenceFrame variant="inline" />;
}
