import { RailScreen } from "./_RailScreen";

export const meta = {
  title: "Rail search finds a label · v2",
  viewport: "laptop",
  description:
    "Typing CHR in the rail: the dropdown offers christmas, highlighted by the down arrow. Superseded by the spec grilling.",
};

export default function Frame() {
  return <RailScreen initialSelected="cc1717-woman-by-christmas-tree" initialQuery="CHR" initialMenu initialActive={0} />;
}
