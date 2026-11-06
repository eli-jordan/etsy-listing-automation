import { RailScreen } from "./_RailScreen";

export const meta = {
  title: "Rail filtered by a label · v2",
  viewport: "laptop",
  description:
    "The christmas pill inside the rail's search box, leaving five templates. Superseded by the spec grilling.",
};

export default function Frame() {
  return <RailScreen initialOn={["christmas"]} initialSelected="cc1717-woman-by-christmas-tree" />;
}
