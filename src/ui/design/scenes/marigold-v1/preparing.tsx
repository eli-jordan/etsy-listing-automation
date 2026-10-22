export const meta = {
  title: "Marigold — preparing · v1",
  viewport: "laptop",
  description:
    "Archived before toolbar, visible mask and field help: Background preparation with step progress, elapsed time and cancellation.",
};
import { MarigoldScreen } from "./_MarigoldScreen";
export default function Preparing() {
  return <MarigoldScreen state="preparing" />;
}
