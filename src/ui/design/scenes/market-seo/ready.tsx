import { MarketSeoScreen } from "../../screens/marketSeo/MarketSeoScreen";
import { brief, listings, research, steps } from "./_fixtures";

export const meta = {
  title: "Market SEO — suggestions ready",
  viewport: "laptop",
  description: "All three nodes done; suggestion drawers open beside the panel, with the top listing expanded to show its tags and lead.",
};

export default function Ready() {
  return <MarketSeoScreen steps={steps.ready} brief={brief} suggestions panel={{ state: { kind: "ready", research }, initialOpen: listings[0].id }} />;
}
