import { ListingFromBatch } from "./_ListingEditor";

export const meta = {
  title: "Listing — use a stale suggestion? · v2",
  viewport: "laptop",
  description:
    "Wireframe state: the one-time warning before accepting an out-of-date AI suggestion in this editor session.",
};

export default function Frame() {
  return <ListingFromBatch confirm />;
}
