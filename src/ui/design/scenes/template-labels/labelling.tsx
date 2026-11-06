import { RailScreen } from "./_RailScreen";

export const meta = {
  title: "Tagging a template",
  viewport: "laptop",
  description:
    "Typing a tag on the open template, with a suggestion and Create. The chip appears once the save lands.",
};

export default function Frame() {
  return <RailScreen initialSelected="cc1717-woman-with-oversize-fit" initialDraft="cos" />;
}
