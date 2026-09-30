import { ActionHeader } from "./_ActionHeader";
import { listing } from "./_fixtures";

export const meta = {
  title: "Header · icon only · v3",
  viewport: "laptop",
  description: "Same head with an icon-only action row; each icon names itself on hover and keyboard focus (Create listing template tip pinned open).",
};

export default function Frame() {
  return <ActionHeader listing={listing} mode="icons" tip="create-template" />;
}
