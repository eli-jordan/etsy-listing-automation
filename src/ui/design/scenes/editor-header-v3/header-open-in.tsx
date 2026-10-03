import { ActionHeader } from "./_ActionHeader";
import { listing } from "./_fixtures";

export const meta = {
  title: "Header · Open in menu · v3",
  viewport: "laptop",
  description: "The Open in dropdown open: Etsy and Printify, each shown only when the listing has an id there.",
};

export default function Frame() {
  return <ActionHeader listing={listing} opened="open-in" />;
}
