import { ListingFromBatch } from "./_ListingEditor";

export const meta = {
  title: "Listing — opened from a batch · v2",
  viewport: "laptop",
  description:
    "Wireframe: batch listing in the editor with Back to batch, Mark reviewed, and a stale title proposal that can still be used.",
};

export default function Frame() {
  return <ListingFromBatch />;
}
