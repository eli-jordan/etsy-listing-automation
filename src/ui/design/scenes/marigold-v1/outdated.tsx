export const meta = {
  title: "Marigold — saved changes · v1",
  viewport: "laptop",
  description:
    "Saved calibration rebuilding on the CPU while the previous preview stays visibly stale.",
};
import { MarigoldScreen } from "./_MarigoldScreen";
export default function Outdated() {
  return <MarigoldScreen state="outdated" />;
}
