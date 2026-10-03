import { ListingSeoReviewScreen } from "./_snapshot/_ListingSeoReviewScreen";
import { failedState } from "./_fixtures";

export const meta = {
  title: "Listing SEO — generation failed · v1",
  viewport: "laptop",
  description: "Hi-fi error state: no invalid proposal reaches the listing after repair and retry fail.",
};

export default function Failed() {
  return <ListingSeoReviewScreen state={failedState} />;
}
