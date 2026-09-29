import { ActionHeader } from "./_ActionHeader";
import { listing } from "./_fixtures";

export const meta = {
  title: "Header · icon + label · v3",
  viewport: "laptop",
  description: "Chosen head: identity row (name, status, auto-save chip, Deploy) over an action row of icon + label actions - Open in, Create listing template, Mark for deletion.",
};

export default function Frame() {
  return <ActionHeader listing={listing} />;
}
