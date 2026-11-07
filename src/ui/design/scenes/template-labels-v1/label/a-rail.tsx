import { RailScreen } from "../_RailScreen";

export const meta = {
  title: "A · Rail tags: labelling · v1",
  viewport: "laptop",
  description:
    "Typing a new free-form tag on the open template, with suggestions and Create. One template at a time. Chosen, before labels moved into the search box.",
};

export default function Frame() {
  return <RailScreen initialSelected="cc1717-woman-with-oversize-fit" initialDraft="cos" />;
}
