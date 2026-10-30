import { ShopPrototype } from "../_prototype";

export const meta = {
  title: "Admin prototype — Settings",
  viewport: "laptop",
  description: "Clickable Settings: provider order, model and effort, list refresh, coupled time limits, batch slider and market weight dividers.",
};

export default function Frame() {
  return <ShopPrototype start={{ section: "settings" }} />;
}
