import { Diagram, Doc, Md } from "@marver-design/marver/content";

export const meta = {
  title: "Batch deployment — first flow",
  viewport: "laptop",
  intent: "diagram",
  description: "A first-pass path from the Listings summary to an applied batch run.",
};

export default function BatchDeployFlow() {
  return (
    <Doc layout="wide">
      <Md>{`# The batch-review path

The compact count earns the click. The review earns the apply.`}</Md>
      <Diagram title="Batch deployment flow">{`
        flowchart LR
          L["Listings :: pending change counts"]:::blue
          R["Batch review :: grouped change rows"]:::orange
          C["Listing comparison :: expanded only when needed"]:::gray
          A["Apply batch :: one reviewed, sequential run"]:::green
          O["Applied state :: outcome inline on the review page"]:::purple
          L --> R
          R --> C
          C --> R
          R --> A --> O
      `}</Diagram>
    </Doc>
  );
}
