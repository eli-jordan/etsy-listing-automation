import { TemplateEditor } from "./_TemplateEditor";

export const meta = {
  title: "Listing template — Variants",
  viewport: "laptop",
  description:
    "Hi-fi: Variants tab is the real VariantsTab; the preview design row (shown open) replaces the listing's design row.",
};

export default function Frame() {
  return <TemplateEditor mode="variants" />;
}
