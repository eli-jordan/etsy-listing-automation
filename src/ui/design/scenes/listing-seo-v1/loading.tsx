import { ListingSeoReviewScreen } from "./_snapshot/_ListingSeoReviewScreen";
import { loadingState } from "./_fixtures";

export const meta = {
  title: "Listing SEO — generating · v1",
  viewport: "laptop",
  description: "Hi-fi loading state: the seller may continue editing while the manual SEO request runs.",
};

export default function Loading() {
  return <ListingSeoReviewScreen state={loadingState} />;
}
