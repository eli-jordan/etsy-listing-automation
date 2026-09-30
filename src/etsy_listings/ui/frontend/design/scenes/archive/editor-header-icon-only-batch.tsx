// Retired in round 4 with its sibling: see editor-header-icon-only.tsx.
import Shell from "../editor-header-v3/_layout";
import { ActionHeader } from "../editor-header-v3/_ActionHeader";
import { batch, listing } from "../editor-header-v3/_fixtures";

export const meta = {
  title: "Editor header - icon-only actions, from a batch",
  viewport: "laptop",
  description: "Retired: the icon-only action row in batch context (Mark reviewed was still a separate button); the icon + label row won.",
};

export default function EditorHeaderIconOnlyBatch() {
  return (
    <Shell>
      <ActionHeader listing={listing} batch={batch} mode="icons" tip="delete" />
    </Shell>
  );
}
