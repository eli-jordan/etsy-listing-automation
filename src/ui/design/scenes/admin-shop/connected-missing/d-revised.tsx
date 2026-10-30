import { ShopPrototype } from "../_prototype";

export const meta = {
  title: "Shops not connected",
  viewport: "laptop",
  description: "Clickable Admin prototype: shops not connected with recovery actions.",
};

export default function Frame() {
  return <ShopPrototype start={{ section: "connected", scenario: "disconnected" }} />;
}
