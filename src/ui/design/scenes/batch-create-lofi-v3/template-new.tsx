import { TemplateEditor } from "./_TemplateEditor";

export const meta = {
  title: "Listing template — new · v3",
  viewport: "laptop",
  description:
    "Wireframe: Save as listing template (or Clone) opens the new template on Variants with the empty name field focused; nothing saves until named.",
};

export default function Frame() {
  return <TemplateEditor mode="new" />;
}
