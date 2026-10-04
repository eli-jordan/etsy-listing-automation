export const meta = {
  title: "Marigold — visible mask editing · v2",
  viewport: "laptop",
  description: "Visible cloth mask with Exclude and Restore tools immediately above the image.",
};
import { MarigoldScreen } from "./_MarigoldScreen";
export default function Frame() {
  return <MarigoldScreen state="edit" initialTool="exclude" initialInfo="mask" />;
}
