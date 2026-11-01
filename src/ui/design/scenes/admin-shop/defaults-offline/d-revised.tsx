import { ShopPrototype } from "../_prototype";

export const meta = {
  title: "Lookup unavailable",
  viewport: "laptop",
  description: "Clickable Admin prototype: lookup unavailable with recovery actions.",
};

export default function Frame() {
  return <ShopPrototype start={{ section: "defaults", scenario: "offline" }} />;
}
