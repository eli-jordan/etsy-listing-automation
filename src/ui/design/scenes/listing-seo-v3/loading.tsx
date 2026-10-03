import { ListingSeoReviewScreen } from "./_snapshot/_ListingSeoReviewScreen";
import { loadingState } from "./_fixtures";

export const meta = {
  title: "Listing SEO — generating · v3",
  viewport: "laptop",
  description: "Hi-fi loading state: AI Mode shows a quiet inline status while leaving listing fields available.",
};

export default function Loading() {
  return <ListingSeoReviewScreen state={loadingState} />;
}
