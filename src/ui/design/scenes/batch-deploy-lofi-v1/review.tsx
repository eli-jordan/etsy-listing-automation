// Retired. The side drawer lost to the bottom sheet; the full frame is preserved at
// design/scenes/archive/batch-deploy-review-side-drawer.tsx and pinned on the archive board.
// This file is a leftover placard because the session that retired it had no shell to delete
// the file. Safe to delete: nothing links here, and it is on no curated board.
export const meta = {
  title: "Batch deployment — review, side drawer (retired) · v1",
  viewport: "laptop",
  description:
    "Retired: the bottom sheet won. Full frame kept at archive/batch-deploy-review-side-drawer. This leftover file is safe to delete.",
};

export default function BatchReviewSideDrawerRetired() {
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: 48,
        background: "#fff",
        color: "#555",
        fontFamily: "system-ui",
        textAlign: "center" as const,
      }}
    >
      <div style={{ border: "1px dashed #aaa", padding: "32px 40px", maxWidth: 520 }}>
        <p style={{ margin: 0, fontSize: 18, color: "#111" }}>
          <strong>Retired frame</strong>
        </p>
        <p style={{ margin: "10px 0 0", lineHeight: 1.5 }}>
          The side drawer was dropped in favour of the bottom sheet. The original is on the archive
          board as <strong>Batch deployment — review (side drawer)</strong>.
        </p>
        <p style={{ margin: "14px 0 0", fontSize: 13 }}>This file can be deleted.</p>
      </div>
    </div>
  );
}
