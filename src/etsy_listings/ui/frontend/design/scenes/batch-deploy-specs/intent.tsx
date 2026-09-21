import { Doc, Md } from "@marver-design/marver/content";

export const meta = {
  title: "Batch deployment — intent",
  viewport: "laptop",
  intent: "spec",
  description: "The operator's single job and the guardrails for reviewing all listing changes.",
};

export default function BatchDeployIntent() {
  return (
    <Doc layout="document">
      <Md>{`# One confident release, across the shop

**Operator's job:** understand the scope of every pending listing change, inspect anything uncertain, then apply the reviewed batch once.

## The promise

- Start from **Listings**, where a compact summary says what will be added, changed, and removed.
- Open one batch review instead of visiting listings one by one.
- Keep each row scannable; reveal the existing side-by-side comparison only on demand.
- Make destructive work unmistakable and separate it from ordinary updates.

## Guardrails

Planning changes nothing. Applying stays sequential, uses the reviewed plan, and reports each listing's outcome without hiding a partial failure.`}</Md>
    </Doc>
  );
}
