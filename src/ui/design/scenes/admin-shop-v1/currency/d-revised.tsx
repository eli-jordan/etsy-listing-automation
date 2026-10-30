import { ShopPrototype } from "../_prototype";

export const meta = {
  title: "Shop tab prototype — Change currency · v1",
  viewport: "laptop",
  description: "Clickable. Starts with the currency warning open; Change stays disabled until the warning is acknowledged.",
};

export default function Frame() {
  return <ShopPrototype start={{ currencyModal: true }} />;
}
