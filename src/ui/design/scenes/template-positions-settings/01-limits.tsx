import { LimitsPanel, saved } from "./_LimitsPanel";

export const meta = {
  title: "5 · Settings — Template rendering",
  viewport: "laptop",
  description: "Prototype start for Settings: drag a slider and the note turns into a warning; Review and save opens the confirmation.",
};

export default function Frame() {
  return (
    <LimitsPanel
      initial={saved}
      onReview="template-positions-settings/02-confirm"
    />
  );
}
