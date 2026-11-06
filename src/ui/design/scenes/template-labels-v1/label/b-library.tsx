import { LibraryScreen } from "../_LibraryScreen";

export const meta = {
  title: "B · Photo library: labelling · v1",
  viewport: "laptop",
  description:
    "Two unlabelled templates selected and labelled together from the bulk bar. A label only some of them hold shows a dash. Not chosen; A won.",
};

export default function Frame() {
  return (
    <LibraryScreen
      initialUnlabelled
      initialPicked={["cc1717-woman-holding-a-bag", "cc1717-woman-in-elevator"]}
      initialMenu
    />
  );
}
