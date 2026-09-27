import { TemplateEditor } from "./_TemplateEditor";

export const meta = {
  title: "Listing template — Variants · v3",
  viewport: "laptop",
  description:
    "Wireframe: Variants tab, identical to the listing editor's; the preview design row (shown open) replaces the listing's design row.",
};

export default function Frame() {
  return <TemplateEditor mode="variants" />;
}
