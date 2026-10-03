export const meta = {
  title: "Batch deployment — planning · v1",
  viewport: "laptop",
  description:
    "Wireframe: the review's planning state makes clear that reading live state has no side effects, and opens the plan itself once it is ready.",
};

export default function BatchReviewLoadingWireframe() {
  return (
    <main
      data-goto="batch-deploy-lofi-v1/review-bottom-sheet"
      style={{
        minHeight: "100vh",
        padding: "56px 14vw",
        background: "#fff",
        color: "#111",
        fontFamily: "system-ui",
      }}
    >
      <p style={{ color: "#555", margin: 0 }}>Listings / Deploy changes</p>
      <h1 style={{ fontSize: 30 }}>Checking all listings…</h1>
      <p style={{ color: "#444" }}>
        Reading Printify and Etsy to prepare your review. Nothing is being changed.
      </p>
      {["Finding pending changes", "Reading listing details", "Preparing comparisons"].map(
        (label) => (
          <div
            key={label}
            style={{
              display: "flex",
              justifyContent: "space-between",
              border: "1px solid #999",
              padding: 16,
              marginTop: 12,
            }}
          >
            <span>{label}</span>
            <span>Loading</span>
          </div>
        ),
      )}
      <p style={{ color: "#555", marginTop: 24 }}>The plan opens as soon as it is ready.</p>
    </main>
  );
}
