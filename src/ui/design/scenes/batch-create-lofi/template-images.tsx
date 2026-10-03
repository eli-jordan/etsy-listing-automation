import { TemplateEditor } from "./_TemplateEditor";

export const meta = {
  title: "Listing template — Listing Images",
  viewport: "laptop",
  description:
    "Hi-fi: Listing Images is the real ImagesTab (its Files group should read This template).",
};

export default function Frame() {
  return <TemplateEditor mode="images" />;
}
