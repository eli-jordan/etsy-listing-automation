import { SuggestedScreen } from "./_SuggestedLocator";

export const meta = {
  title: "Search offers a label to add · v2",
  viewport: "laptop",
  description:
    "Typing flat offers the flat lay label, which would narrow the christmas filter to one template. Superseded: labels moved into the search box.",
};

export default function Frame() {
  return <SuggestedScreen focus="cc1717-red-shirt-flat-lay" initialQuery="flat" />;
}
