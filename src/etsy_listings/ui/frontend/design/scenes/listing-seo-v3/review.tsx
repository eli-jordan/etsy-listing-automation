import { ListingSeoReviewScreen } from "./_snapshot/_ListingSeoReviewScreen";
import { reviewState } from "./_fixtures";

export const meta = {
  title: "Listing SEO — proposal review · v3",
  viewport: "laptop",
  description: "Working clickable frame: choose among three titles and leads or compose 13 tags from 20 ranked suggestions.",
};

export default function Review() {
  return <ListingSeoReviewScreen state={reviewState} />;
}
