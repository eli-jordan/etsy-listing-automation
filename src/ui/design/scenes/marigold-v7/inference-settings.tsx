export const meta = {
  title: "Marigold — Advanced inference · v7",
  viewport: "laptop",
  description:
    "Selected settings dialog with matching Inference steps and Ensemble size labels and help cards.",
};
import { MarigoldScreen } from "./_MarigoldScreen";
export default function Frame() {
  return <MarigoldScreen state="edit" initialInferenceOpen />;
}
