// v1 tracks the app components; exact state: git
import { RailScreen } from "../_RailScreen";

export const meta = {
  title: "A · Rail tags: filtering · v1",
  viewport: "laptop",
  description:
    "Free-form tags as pills on today's rail, with Christmas on. The workbench stays exactly where it is. Chosen, before labels moved into the search box.",
};

export default function Frame() {
  return <RailScreen initialOn={["christmas"]} initialSelected="cc1717-woman-by-christmas-tree" />;
}
