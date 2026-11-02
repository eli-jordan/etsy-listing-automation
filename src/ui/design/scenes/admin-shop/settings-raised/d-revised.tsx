import { ShopPrototype } from "../_prototype";

export const meta = {
  title: "Run limit raised automatically",
  viewport: "laptop",
  description: "Clickable Admin prototype: run limit raised automatically with recovery actions.",
};

export default function Frame() {
  return <ShopPrototype start={{ section: "settings", scenario: "raised" }} />;
}
