import { Diagram, Doc, Md } from "@marver-design/marver/content";

export const meta = {
  title: "Batch creation — flow",
  viewport: "laptop",
  intent: "diagram",
  description:
    "Flow (round 4): template, staging, batch summary, and the listing editor with its way back to the batch.",
};

export default function BatchCreateFlow() {
  return (
    <Doc layout="wide">
      <Md>{`# From a design drop to reviewable drafts

The template carries the production settings. Staging earns the confirm. The batch summary is the one place to review what was created. Nothing here deploys.`}</Md>
      <Diagram title="Batch creation flow">{`
        flowchart LR
          E["Listing editor :: Save as listing template"]:::gray
          N0["New template :: name it to save"]:::gray
          T["Listing templates :: cards are drop targets"]:::blue
          N["New batch :: one template, one ZIP or loose PNGs"]:::blue
          X["Upload refused :: over 25, mixed, unsafe ZIP"]:::red
          S["Staging :: validate, dedupe, name"]:::orange
          B["Batch summary :: AI queue, retry, reviewed"]:::green
          L["Listing editor :: back to batch, mark reviewed"]:::purple
          E --> N0 --> T
          T --> N
          T -- "drop on card" --> S
          T -- "resume staging" --> S
          N --> S
          N --> X --> N
          S -- "Create listings" --> B
          B --> L
          L -- "Back to batch" --> B
      `}</Diagram>
      <Md>{`**Settled in round 1:** a drop on a template card goes straight to Staging. No batch filter on Listings; the batch summary is the review surface. An unconfirmed staging session shows as a row in Recent batches.

**Settled in round 2:** the template editor mirrors the listing editor tab for tab. Recent batches carry a status (Staging, Drafting, In review, Complete, Stopped). An out-of-date AI suggestion can be used directly; the drawer's wording is the warning, with no confirmation dialog (the spec asks for one).

**Settled in round 3:** the template editor head has no actions (Clone, Delete and Start batch stay on the Listing templates page). A batch is Complete once every listing is reviewed; deploying is not required. The frames are hi-fi, mounted from the app's real components.`}</Md>
    </Doc>
  );
}
