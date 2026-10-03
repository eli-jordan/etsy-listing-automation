import { ActionHeader } from "./_ActionHeader";
import { listing } from "./_fixtures";

export const meta = {
  title: "Header · file card · v3",
  viewport: "laptop",
  description: "The auto-save chip beside the status opened into the listing file card: listing.yaml path with Copy, when it saved, when it last deployed.",
};

export default function Frame() {
  return <ActionHeader listing={listing} opened="file-card" />;
}
