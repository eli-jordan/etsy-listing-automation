import { TemplateEditor } from "./_TemplateEditor";

export const meta = {
  title: "Listing template — change not saved",
  viewport: "laptop",
  description:
    "Hi-fi state: an edit that makes the template incomplete is held and flagged; the last complete version stays saved.",
};

export default function Frame() {
  return <TemplateEditor mode="unsaved" />;
}
