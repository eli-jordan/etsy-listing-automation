import { ActionHeader } from "./_ActionHeader";
import { listing } from "./_fixtures";

export const meta = {
  title: "Header",
  viewport: "laptop",
  description: "Chosen head (round 4): identity row (name, status, auto-save chip, Deploy) over an icon + label action row - Open in, Create listing template, Mark for deletion.",
};

export default function Frame() {
  return <ActionHeader listing={listing} />;
}
