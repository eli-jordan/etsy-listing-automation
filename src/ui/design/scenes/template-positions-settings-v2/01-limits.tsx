import { LimitsPanel } from "./_LimitsPanel";

export const meta = {
  title: "7 · Settings — limits, edited · v2",
  viewport: "laptop",
  description: "Admin > Settings > Template rendering with Largest raised to 120%: the cost line turns into a warning and saving goes through a review.",
};

export default function Frame() {
  return (
    <LimitsPanel
      initial={{ smallest: 80, largest: 120, offset: 10, tilt: 15 }}
      onReview="template-positions-settings-v2/02-confirm"
    />
  );
}
