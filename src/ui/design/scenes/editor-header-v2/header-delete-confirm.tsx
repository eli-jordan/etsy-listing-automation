import { ActionHeader } from "./_ActionHeader";
import { listing } from "./_fixtures";

export const meta = {
  title: "Header · confirm deletion · v2",
  viewport: "laptop",
  description: "Mark for deletion asks first, with the Listings table's own dialog and wording; Delete replaces it for a listing with nothing on Etsy or Printify.",
};

export default function Frame() {
  return <ActionHeader listing={listing} opened="confirm-delete" />;
}
