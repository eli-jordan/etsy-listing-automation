export const meta = {
  title: "Marigold — preparing · v2",
  viewport: "laptop",
  description: "Background preparation with step progress, elapsed time and cancellation.",
};
import { MarigoldScreen } from "./_MarigoldScreen";
export default function Preparing() {
  return <MarigoldScreen state="preparing" />;
}
