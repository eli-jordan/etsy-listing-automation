import { MarketSeoScreen } from "../../screens/marketSeo/MarketSeoScreen";
import { brief, research, steps } from "./_fixtures";

export const meta = {
  title: "Market SEO — writing suggestions",
  viewport: "laptop",
  description: "Market research done and the top listings panel filled; SEO suggestions is the glowing last node.",
};

export default function Suggesting() {
  return <MarketSeoScreen steps={steps.suggesting} brief={brief} elapsed="0:14" panel={{ state: { kind: "ready", research } }} />;
}
