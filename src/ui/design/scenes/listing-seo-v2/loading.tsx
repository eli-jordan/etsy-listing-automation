import { ListingSeoReviewScreen } from "./_snapshot/_ListingSeoReviewScreen";
import { loadingState } from "./_fixtures";

export const meta = {
  title: "Listing SEO — generating · v2",
  viewport: "laptop",
  description: "Hi-fi loading state: a quiet inline status leaves the listing fields available while generation runs.",
};

export default function Loading() {
  return <ListingSeoReviewScreen state={loadingState} />;
}
