export const meta = {
  title: "Marigold — full-quality preview · v1",
  viewport: "laptop",
  description:
    "Archived before toolbar, visible mask and field help: Prepared maps shared across colours in the existing full-quality Preview tab.",
};
import { MarigoldScreen } from "./_MarigoldScreen";
export default function Preview() {
  return <MarigoldScreen state="preview" />;
}
