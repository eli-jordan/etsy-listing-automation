import { TemplateEditor } from "./_TemplateEditor";

export const meta = {
  title: "Listing template — Pricing · v3",
  viewport: "laptop",
  description:
    "Wireframe: Pricing tab, identical to the listing editor's plan and per-size prices.",
};

export default function Frame() {
  return <TemplateEditor mode="pricing" />;
}
