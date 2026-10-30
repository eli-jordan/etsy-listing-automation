import { ShopPrototype } from "../_prototype";

export const meta = {
  title: "Admin prototype — Settings · v1",
  viewport: "laptop",
  description: "Clickable. Starts on Settings: drag providers to reorder, switch them, pick model and reasoning, step batch size, drag the market weight dividers.",
};

export default function Frame() {
  return <ShopPrototype start={{ section: "settings" }} />;
}
