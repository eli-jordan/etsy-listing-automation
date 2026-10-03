import { ActionHeader } from "./_ActionHeader";
import { listing } from "./_fixtures";

export const meta = {
  title: "Header · file card",
  viewport: "laptop",
  description: "The auto-save chip beside the status opened into the listing file card: listing.yaml path with Copy, and when it saved.",
};

export default function Frame() {
  return <ActionHeader listing={listing} opened="file-card" />;
}
