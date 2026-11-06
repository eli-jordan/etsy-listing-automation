import { SuggestedScreen } from "./_SuggestedLocator";

export const meta = {
  title: "Search offers a label to swap · v2",
  viewport: "laptop",
  description:
    "Typing sum finds nothing under christmas, so summer is offered in its place and the matches show under Other templates. Superseded: labels moved into the search box.",
};

export default function Frame() {
  return <SuggestedScreen focus="cc1717-hanging-under-umbrella" initialQuery="sum" />;
}
