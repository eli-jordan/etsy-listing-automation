export const meta = {
  title: "Marigold â€” preparation failed · v4",
  viewport: "laptop",
  description:
    "An actionable preparation failure with Retry and existing placement controls retained.",
};
import { MarigoldScreen } from "./_MarigoldScreen";
export default function Failed() {
  return <MarigoldScreen state="failed" />;
}
