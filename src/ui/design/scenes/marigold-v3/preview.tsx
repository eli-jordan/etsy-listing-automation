export const meta = {
  title: "Marigold â€” full-quality preview · v3",
  viewport: "laptop",
  description: "Prepared maps shared across colours in the existing full-quality Preview tab.",
};
import { MarigoldScreen } from "./_MarigoldScreen";
export default function Preview() {
  return <MarigoldScreen state="preview" />;
}
