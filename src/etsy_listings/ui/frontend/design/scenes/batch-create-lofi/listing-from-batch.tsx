import { ListingFromBatch } from "./_ListingEditor";

export const meta = {
  title: "Listing — opened from a batch",
  viewport: "laptop",
  description:
    "Hi-fi: batch listing in the editor with Back to batch, Mark reviewed, and an out-of-date title proposal that can still be used directly.",
};

export default function Frame() {
  return <ListingFromBatch />;
}
