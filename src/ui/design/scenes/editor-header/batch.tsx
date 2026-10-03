import { ActionHeader } from "./_ActionHeader";
import { batch, listing } from "./_fixtures";

export const meta = {
  title: "Header · from a batch",
  viewport: "laptop",
  description: "Opened from a batch: Back to batch takes the crumb place, and Mark reviewed joins the action row beside Mark for deletion, styled like it.",
};

export default function Frame() {
  return <ActionHeader listing={listing} batch={batch} />;
}
