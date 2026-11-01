import { ShopPrototype } from "../_prototype";

export const meta = {
  title: "Shop tab prototype — Listing defaults, Custom",
  viewport: "laptop",
  description: "Clickable. Starts on Listing defaults with Custom: the three fields as selectors; Fulfilment and policies below.",
};

export default function Frame() {
  return <ShopPrototype start={{ section: "defaults", tier: "custom" }} />;
}
