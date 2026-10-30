import { ShopPrototype } from "../_prototype";

export const meta = {
  title: "Model discovery unavailable",
  viewport: "laptop",
  description: "Clickable Admin prototype: model discovery unavailable with recovery actions.",
};

export default function Frame() {
  return <ShopPrototype start={{ section: "settings", scenario: "discovery" }} />;
}
