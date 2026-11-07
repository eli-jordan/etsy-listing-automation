import { SuggestedScreen } from "./_SuggestedLocator";

export const meta = {
  title: "Typing finds a label · v3",
  viewport: "laptop",
  description:
    "Typing CHR with no labels on: the dropdown offers christmas, highlighted by the down arrow. Superseded by the spec grilling.",
};

export default function Frame() {
  return <SuggestedScreen focus="cc1717-woman-by-christmas-tree" initialOn={[]} initialQuery="CHR" initialMenu initialActive={0} />;
}
