import { Diagram, Doc } from "@marver-design/marver/content";

export const meta = {
  title: "Listing SEO — agreed flow",
  viewport: "laptop",
  intent: "diagram",
  description: "The seller’s manual generation and field-by-field approval flow before the wireframes.",
};

export default function Flow() {
  return (
    <Doc layout="wide">
      <Diagram title="SEO proposal flow">{`
        flowchart LR
          R["Ready :: design + brief present"]:::blue --> G["AI Mode :: manual request"]:::blue
          G --> L["Generating :: snapshot listing facts"]:::orange
          L --> P["Suggestions :: 3 titles + 3 leads + 20 tags"]:::green
          P --> A["Choose :: title or lead applies immediately"]:::green
          P --> T["Choose tags :: one-by-one or best 13"]:::green
          P --> S["Stale :: inputs changed"]:::orange
          S --> G
          L --> E["Retry :: invalid or failed response"]:::red
          E --> G
      `}</Diagram>
    </Doc>
  );
}
