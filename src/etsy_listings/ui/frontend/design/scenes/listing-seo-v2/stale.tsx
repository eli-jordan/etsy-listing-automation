import { ListingSeoReviewScreen } from "./_snapshot/_ListingSeoReviewScreen";
import { staleState } from "./_fixtures";

export const meta = {
  title: "Listing SEO — stale · v2",
  viewport: "laptop",
  description: "Hi-fi stale state: attached drawers remain dismissible but disable acceptance until regenerated.",
};

export default function Stale() {
  return <ListingSeoReviewScreen state={staleState} />;
}
