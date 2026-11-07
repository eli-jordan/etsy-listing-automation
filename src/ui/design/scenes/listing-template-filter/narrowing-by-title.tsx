import { SuggestedScreen } from "./_SuggestedLocator";

export const meta = {
  title: "Text narrows the label",
  viewport: "laptop",
  description:
    "The theme:christmas pill plus the plain text tree: no label matches, so it stays text and narrows five templates to two.",
};

export default function Frame() {
  return <SuggestedScreen focus="cc1717-woman-in-cardigan-by-tree" initialOn={["theme:christmas"]} initialQuery="tree" />;
}
