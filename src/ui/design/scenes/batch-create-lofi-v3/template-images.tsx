import { TemplateEditor } from "./_TemplateEditor";

export const meta = {
  title: "Listing template — Listing Images · v3",
  viewport: "laptop",
  description:
    "Wireframe: Listing Images as in the listing editor (Files group reads This template).",
};

export default function Frame() {
  return <TemplateEditor mode="images" />;
}
