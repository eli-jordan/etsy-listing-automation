import { TemplateEditor } from "./_TemplateEditor";

export const meta = {
  title: "Listing template editor · v2",
  viewport: "laptop",
  description:
    "Wireframe: editing a template's gallery, previewed with the calibrator's test-design picker (Bundled grid by default).",
};

export default function Frame() {
  return <TemplateEditor mode="images" />;
}
