import { ShopPrototype } from "../_prototype";

export const meta = {
  title: "AI time limits",
  viewport: "laptop",
  description: "Clickable Admin prototype: ai time limits with recovery actions.",
};

export default function Frame() {
  return <ShopPrototype start={{ section: "settings", scenario: "limits" }} />;
}
