import { ActionHeader } from "./_ActionHeader";
import { listing } from "./_fixtures";

export const meta = {
  title: "Header · resting · v2",
  viewport: "laptop",
  description: "Chosen head: identity row (name, status, Deploy) over a quiet action row - Open in, Create listing template, Mark for deletion, and the saved state.",
};

export default function Frame() {
  return <ActionHeader listing={listing} />;
}
