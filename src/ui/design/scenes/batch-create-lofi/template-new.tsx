import { TemplateEditor } from "./_TemplateEditor";

export const meta = {
  title: "Listing template — new",
  viewport: "laptop",
  description:
    "Hi-fi: Save as listing template (or Clone) opens the new template (real EditableName, empty and focused); nothing saves until named.",
};

export default function Frame() {
  return <TemplateEditor mode="new" />;
}
