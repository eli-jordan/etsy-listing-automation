import { ListingSeoReviewScreen } from "./_snapshot/_ListingSeoReviewScreen";
import { staleState } from "./_fixtures";

export const meta = {
  title: "Listing SEO — stale · v1",
  viewport: "laptop",
  description: "Hi-fi stale state: a pending proposal is retained but needs explicit regeneration after relevant facts change.",
};

export default function Stale() {
  return <ListingSeoReviewScreen state={staleState} />;
}
