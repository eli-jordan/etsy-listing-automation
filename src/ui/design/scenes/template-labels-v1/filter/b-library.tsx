import { LibraryScreen } from "../_LibraryScreen";

export const meta = {
  title: "B · Photo library: filtering · v1",
  viewport: "laptop",
  description:
    "The page opens on a photo grid with grouped label filters beside it, here Female and Christmas. Not chosen; A won.",
};

export default function Frame() {
  return <LibraryScreen initialSelection={{ model: ["Female"], theme: ["Christmas"] }} />;
}
