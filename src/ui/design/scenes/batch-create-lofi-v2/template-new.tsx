import { TemplateEditor } from "./_TemplateEditor";

export const meta = {
  title: "Listing template — new · v2",
  viewport: "laptop",
  description:
    "Wireframe: Save as listing template (or Clone) opens the new template with the cursor in the name field; nothing saves until it is named.",
};

export default function Frame() {
  return <TemplateEditor mode="new" />;
}
