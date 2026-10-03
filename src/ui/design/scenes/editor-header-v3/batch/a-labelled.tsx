import { ActionHeader } from "../_ActionHeader";
import { batch, listing } from "../_fixtures";

export const meta = {
  title: "Batch · icon + label · v3",
  viewport: "laptop",
  description: "Opened from a batch: Back to batch takes the crumb place; Mark reviewed ends the action row under Deploy. Actions are icon + label.",
};

export default function Frame() {
  return <ActionHeader listing={listing} batch={batch} />;
}
