import { ShopPrototype } from "../_prototype";

export const meta = {
  title: "Settings changed on disk",
  viewport: "laptop",
  description: "Clickable Admin prototype: settings changed on disk with recovery actions.",
};

export default function Frame() {
  return <ShopPrototype start={{ section: "settings", scenario: "conflict" }} />;
}
