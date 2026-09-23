export const meta = {
  title: "Listing SEO — stale suggestion · v2",
  viewport: "laptop",
  description: "Wireframe: stale attached drawers can be rejected but require regeneration before acceptance.",
};

export default function Stale() {
  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 660, margin: "32px auto", padding: 24 }}>
      <header style={{ display: "flex", justifyContent: "space-between" }}><h1>Listing details</h1><button type="button">✦ Regenerate</button></header>
      <section style={{ marginTop: 28 }}>
        <strong>Title</strong>
        <div style={{ border: "1px solid #777", padding: 10, marginTop: 6 }}>Take A Hike Mountain Tee</div>
        <aside style={{ border: "1px solid #999", borderTop: 0, margin: "0 8px", padding: 10 }}>
          <small>Suggestion is out of date</small>
          <span style={{ float: "right" }}><button type="button">× Reject</button> <button type="button" disabled>✓ Accept</button></span>
          <p>Retro Take A Hike Mountain Graphic Tee</p>
        </aside>
      </section>
    </main>
  );
}
