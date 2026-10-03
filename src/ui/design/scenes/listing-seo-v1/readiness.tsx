import { ListingSeoReviewScreen } from "./_snapshot/_ListingSeoReviewScreen";
import { readinessState } from "./_fixtures";

export const meta = {
  title: "Listing SEO — not ready · v1",
  viewport: "laptop",
  description: "Hi-fi empty state: the desktop SEO panel explains why generation is unavailable on hover.",
};

export default function Readiness() {
  return <ListingSeoReviewScreen state={readinessState} />;
}
