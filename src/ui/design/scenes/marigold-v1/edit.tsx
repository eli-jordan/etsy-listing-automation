// v1 tracks live app components; exact state: git.
export const meta = {
  title: "Marigold — placement & masks · v1",
  viewport: "laptop",
  description:
    "Archived before toolbar, visible mask and field help: The current template workbench with Marigold controls and fast placement preview.",
};
import { MarigoldScreen } from "./_MarigoldScreen";
export default function Edit() {
  return <MarigoldScreen state="edit" />;
}
