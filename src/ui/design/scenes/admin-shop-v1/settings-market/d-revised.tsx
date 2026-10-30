import { ShopPrototype } from "../_prototype";

export const meta = {
  title: "Admin prototype — Settings, market scoring · v1",
  viewport: "laptop",
  description: "Clickable. Same Settings tab scrolled to Market SEO scoring: drag the dividers in the bar to share out 100%.",
};

export default function Frame() {
  return <ShopPrototype start={{ section: "settings", scrollTo: "market" }} />;
}
