import { RailScreen } from "./_RailScreen";

export const meta = {
  title: "Rail search finds a label",
  viewport: "laptop",
  description:
    "Typing CHR in the rail: the dropdown offers theme:christmas, highlighted by the down arrow.",
};

export default function Frame() {
  return <RailScreen initialSelected="cc1717-woman-by-christmas-tree" initialQuery="CHR" initialMenu initialActive={0} />;
}
