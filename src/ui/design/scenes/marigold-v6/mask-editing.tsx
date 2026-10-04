export const meta = {
  title: "Marigold — visible mask editing · v6",
  viewport: "laptop",
  description:
    "Selected floating dock with Mask and Unmask brushes; transparent red marks hidden print.",
};
import { MarigoldScreen } from "./_MarigoldScreen";
export default function Frame() {
  return <MarigoldScreen state="edit" initialTool="exclude" />;
}
