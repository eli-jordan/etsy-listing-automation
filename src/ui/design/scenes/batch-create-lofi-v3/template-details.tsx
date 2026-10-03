import { TemplateEditor } from "./_TemplateEditor";

export const meta = {
  title: "Listing template — Listing Details · v3",
  viewport: "laptop",
  description:
    "Wireframe: Listing Details without brief, title, tags, lead or AI Mode; description body, preview, section and materials remain.",
};

export default function Frame() {
  return <TemplateEditor mode="details" />;
}
