// Retired in round 4: the icon + label action row won - words carry the
// actions without a hover, and the row has room for them.
import Shell from "../editor-header-v3/_layout";
import { ActionHeader } from "../editor-header-v3/_ActionHeader";
import { listing } from "../editor-header-v3/_fixtures";

export const meta = {
  title: "Editor header - icon-only actions",
  viewport: "laptop",
  description: "Retired: icon-only action row with hover/focus tips; the icon + label row won - words need no hover and fit the row.",
};

export default function EditorHeaderIconOnly() {
  return (
    <Shell>
      <ActionHeader listing={listing} mode="icons" tip="create-template" />
    </Shell>
  );
}
