import { Doc, Md } from "@marver-design/marver/content";

export const meta = {
  title: "Listing SEO — product decisions",
  viewport: "laptop",
  intent: "spec",
  description: "The approved boundaries for AI-assisted SEO copy on a desktop listing-detail screen.",
};

export default function Decisions() {
  return (
    <Doc layout="document">
      <Md>{`# Reviewable, human-owned listing copy

**AI Mode** is manual and available only when a design and listing brief exist. It uses workspace and listing facts—never external performance data in v1.

## Proposal lifecycle

- Keep the generated proposal in browser storage only.
- Compare a frozen input snapshot before accepting it; changed inputs make it stale.
- Generate three title choices and three description-lead choices. Clicking one applies it and closes the drawer; Reject all closes it unchanged.
- Generate 20 ranked tags. Clicking a tag toggles it directly into the listing, while Accept best 13 applies the top-ranked set.
- Accepted values autosave and belong to the seller; regeneration never overwrites them.

## Description model

The final Etsy description joins a non-empty SEO lead and body with one blank line. The body is exactly one source: inline copy or a workspace-relative \`common-copy/\` file that targets descriptions.

## Failure boundary

Normalize harmless formatting, retry invalid model output once, then show a visible failure. Warnings inform the seller but never block acceptance.`}</Md>
    </Doc>
  );
}
