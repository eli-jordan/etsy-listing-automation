import { RailScreen } from "./_RailScreen";

export const meta = {
  title: "Rail filtered by a label",
  viewport: "laptop",
  description:
    "The theme:christmas pill inside the rail's search box, leaving five templates.",
};

export default function Frame() {
  return <RailScreen initialOn={["theme:christmas"]} initialSelected="cc1717-woman-by-christmas-tree" />;
}
