import { MarketSeoScreen } from "../../screens/marketSeo/MarketSeoScreen";
import { brief, queries, steps } from "./_fixtures";

export const meta = {
  title: "Market SEO — researching the market",
  viewport: "laptop",
  description: "Brief drafted; market research is the glowing middle node, and the panel shows the three Etsy searches loading.",
};

export default function Researching() {
  return <MarketSeoScreen steps={steps.researching} brief={brief} elapsed="0:06" panel={{ state: { kind: "loading", queries } }} />;
}
