import { ShopPrototype } from "../_prototype";

export const meta = {
  title: "Invalid settings file",
  viewport: "laptop",
  description: "Clickable Admin prototype: invalid settings file with recovery actions.",
};

export default function Frame() {
  return <ShopPrototype start={{ section: "settings", scenario: "invalid" }} />;
}
