import { ShopPrototype } from "../_prototype";

export const meta = {
  title: "Shop tab prototype — Listing defaults, Print on demand",
  viewport: "laptop",
  description: "Clickable. Starts on Listing defaults with Print on demand: the three fields it sets shown as values.",
};

export default function Frame() {
  return <ShopPrototype start={{ section: "defaults", tier: "pod" }} />;
}
