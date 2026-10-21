// v2 tracks live app components; exact state: git.
export const meta = {
  title: "Marigold — placement & masks · v2",
  viewport: "laptop",
  description: "The current template workbench with Marigold controls and fast placement preview.",
};
import { MarigoldScreen } from "./_MarigoldScreen";
export default function Edit() {
  return <MarigoldScreen state="edit" />;
}
