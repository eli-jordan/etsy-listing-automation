export const meta = {
  title: "Listing SEO — generating",
  viewport: "laptop",
  description: "Wireframe: the sparkle action and one quiet status line show generation without displacing the fields.",
};

export default function Generating() {
  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 660, margin: "32px auto", padding: 24 }}>
      <header style={{ display: "flex", justifyContent: "space-between" }}><h1>Listing details</h1><button type="button" disabled>✦ AI Mode</button></header>
      <p style={{ border: "1px solid #aaa", padding: 8 }}>● Creating suggestions from the current listing…</p>
      <p style={{ border: "1px solid #777", padding: 12, marginTop: 24 }}>Title</p>
      <p style={{ border: "1px solid #777", padding: 12 }}>Tags</p>
      <p style={{ border: "1px solid #777", padding: 12 }}>Description lead</p>
    </main>
  );
}
