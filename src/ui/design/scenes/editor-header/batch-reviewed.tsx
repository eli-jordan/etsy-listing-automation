import { ActionHeader } from "./_ActionHeader";
import { batch, listing } from "./_fixtures";

export const meta = {
  title: "Header · from a batch, reviewed",
  viewport: "laptop",
  description: "After Mark reviewed: the action reads Reviewed in the settled green; pressing it again marks the listing as needing review.",
};

export default function Frame() {
  return <ActionHeader listing={listing} batch={{ ...batch, reviewed: true }} />;
}
