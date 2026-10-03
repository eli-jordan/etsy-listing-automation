import { ActionHeader } from "./_ActionHeader";
import { listing } from "./_fixtures";

export const meta = {
  title: "Header · marked for deletion · v3",
  viewport: "laptop",
  description: "After confirming: status reads Pending delete and the action becomes Undo mark for deletion until the next deploy retracts it.",
};

export default function Frame() {
  return <ActionHeader listing={listing} marked />;
}
