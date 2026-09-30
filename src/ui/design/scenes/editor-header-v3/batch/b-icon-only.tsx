import { ActionHeader } from "../_ActionHeader";
import { batch, listing } from "../_fixtures";

export const meta = {
  title: "Batch · icon only · v3",
  viewport: "laptop",
  description: "Opened from a batch, icon-only action row (Mark for deletion tip pinned open); Back to batch and Mark reviewed keep their words (they are navigation and a workflow step, not listing actions).",
};

export default function Frame() {
  return <ActionHeader listing={listing} batch={batch} mode="icons" tip="delete" />;
}
