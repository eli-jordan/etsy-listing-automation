import { ListingSeoReviewScreen } from "./_snapshot/_ListingSeoReviewScreen";
import { reviewState } from "./_fixtures";

export const meta = {
  title: "Listing SEO — proposal review · v1",
  viewport: "laptop",
  description: "Working hi-fi frame: the approved desktop review surface for one listing’s AI SEO proposal.",
};

export default function Review() {
  return <ListingSeoReviewScreen state={reviewState} />;
}
