import { RailScreen } from "./_RailScreen";

export const meta = {
  title: "A tag that cannot be saved",
  viewport: "laptop",
  description:
    "An invalid tag keeps the typed text and shows why in place of Create.",
};

export default function Frame() {
  return <RailScreen initialSelected="cc1717-woman-with-oversize-fit" initialDraft="xmas!" />;
}
