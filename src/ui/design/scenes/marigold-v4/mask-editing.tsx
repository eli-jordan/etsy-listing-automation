export const meta = {
  title: "Marigold â€” visible mask editing · v4",
  viewport: "laptop",
  description:
    "Selected floating dock with Mask and Unmask brushes; transparent red marks hidden print.",
};
import { MarigoldScreen } from "./_MarigoldScreen";
export default function Frame() {
  return <MarigoldScreen state="edit" initialTool="exclude" />;
}
