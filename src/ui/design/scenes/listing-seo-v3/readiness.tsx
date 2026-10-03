import { ListingSeoReviewScreen } from "./_snapshot/_ListingSeoReviewScreen";
import { readinessState } from "./_fixtures";

export const meta = {
  title: "Listing SEO — not ready · v3",
  viewport: "laptop",
  description: "Hi-fi empty state: a subtle disabled sparkle action explains its missing inputs on hover.",
};

export default function Readiness() {
  return <ListingSeoReviewScreen state={readinessState} />;
}
