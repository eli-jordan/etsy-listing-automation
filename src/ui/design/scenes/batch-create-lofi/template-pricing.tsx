import { TemplateEditor } from "./_TemplateEditor";

export const meta = {
  title: "Listing template — Pricing",
  viewport: "laptop",
  description:
    "Hi-fi: Pricing is the real PricingTab with the template's plan and per-size prices.",
};

export default function Frame() {
  return <TemplateEditor mode="pricing" />;
}
