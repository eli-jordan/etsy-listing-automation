import { ActionHeader } from "./_ActionHeader";
import { listing } from "./_fixtures";

export const meta = {
  title: "Header · file card · v2",
  viewport: "laptop",
  description: "Saved 3 mins ago opened into the listing file card: the listing.yaml path with Copy, when it saved, when it last deployed.",
};

export default function Frame() {
  return <ActionHeader listing={listing} opened="file-card" />;
}
