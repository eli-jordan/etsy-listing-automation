import { TableScreen } from "../_TableScreen";

export const meta = {
  title: "C · Attribute table: filtering · v1",
  viewport: "laptop",
  description:
    "Every template a row and every label group a column, on the saved Christmas view with the Model filter open. Not chosen; A won.",
};

export default function Frame() {
  return <TableScreen initialView="christmas" initialOpen={{ kind: "filter", group: "model" }} />;
}
