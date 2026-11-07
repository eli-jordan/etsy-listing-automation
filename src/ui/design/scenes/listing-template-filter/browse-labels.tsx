import { OpenLabelMenu } from "../../components/_OpenLabelMenu";
import { SuggestedScreen } from "./_SuggestedLocator";

export const meta = {
  title: "Every label, grouped",
  viewport: "laptop",
  description:
    "Clicking the box lists every other label under its prefix, with plain tags under Other.",
};

export default function Frame() {
  return (
    <OpenLabelMenu>
      <SuggestedScreen
        focus="cc1717-woman-by-christmas-tree"
        initialOn={["theme:christmas"]}
      />
    </OpenLabelMenu>
  );
}
