import { ListingSeoReviewScreen } from "./_snapshot/_ListingSeoReviewScreen";
import { failedState } from "./_fixtures";

export const meta = {
  title: "Listing SEO — generation failed · v3",
  viewport: "laptop",
  description: "Hi-fi error state: a small inline recovery note appears above unchanged listing fields.",
};

export default function Failed() {
  return <ListingSeoReviewScreen state={failedState} />;
}
