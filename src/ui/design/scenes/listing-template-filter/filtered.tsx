import { SuggestedScreen } from "./_SuggestedLocator";

export const meta = {
  title: "Label pill in the search box",
  viewport: "laptop",
  description:
    "The theme:christmas pill inside the search box, leaving five templates.",
};

export default function Frame() {
  return <SuggestedScreen focus="cc1717-woman-with-peace-sign-and-mug" initialOn={["theme:christmas"]} initialOpen="cc1717-woman-with-peace-sign-and-mug" />;
}
