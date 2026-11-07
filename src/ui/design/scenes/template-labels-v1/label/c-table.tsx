import { TableScreen } from "../_TableScreen";

export const meta = {
  title: "C · Attribute table: labelling · v1",
  viewport: "laptop",
  description:
    "Filling a gap in place: the Needs labels view with one Model cell open. Not chosen; A won.",
};

export default function Frame() {
  return (
    <TableScreen
      initialView="gaps"
      initialOpen={{ kind: "cell", group: "model", name: "cc1717-man-with-tattoos-standing" }}
    />
  );
}
