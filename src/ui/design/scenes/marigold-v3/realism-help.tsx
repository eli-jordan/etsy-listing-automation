export const meta = {
  title: "Marigold â€” realism help · v3",
  viewport: "laptop",
  description: "Click-to-open explanations for lighting, fabric texture and print shine.",
};
import { MarigoldScreen } from "./_MarigoldScreen";
export default function Frame() {
  return <MarigoldScreen state="edit" initialInfo="shading" />;
}
