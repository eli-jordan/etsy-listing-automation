import { OpenLabelMenu } from "../../components/_OpenLabelMenu";
import { SuggestedScreen } from "./_SuggestedLocator";

export const meta = {
  title: "Typing finds a label",
  viewport: "laptop",
  description:
    "Typing CHR with no pills: the dropdown offers theme:christmas, highlighted by the down arrow.",
};

export default function Frame() {
  return (
    <OpenLabelMenu highlightFirst>
      <SuggestedScreen
        focus="cc1717-woman-by-christmas-tree"
        initialQuery="CHR"
      />
    </OpenLabelMenu>
  );
}
