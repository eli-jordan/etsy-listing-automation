export const meta = {
  title: "Marigold — preparation failed · v2",
  viewport: "laptop",
  description:
    "An actionable preparation failure with Retry and existing placement controls retained.",
};
import { MarigoldScreen } from "./_MarigoldScreen";
export default function Failed() {
  return <MarigoldScreen state="failed" />;
}
