export const meta = {
  title: "Marigold — saved changes · v4",
  viewport: "laptop",
  description:
    "Maps are current after the automatic CPU rebuild; stale renders use the existing red Re-render button.",
};
import { MarigoldScreen } from "./_MarigoldScreen";
export default function Outdated() {
  return <MarigoldScreen state="outdated" />;
}
