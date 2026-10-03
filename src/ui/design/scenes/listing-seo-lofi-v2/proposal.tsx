export const meta = {
  title: "Listing SEO — attached suggestions · v2",
  viewport: "laptop",
  description: "Wireframe: each generated value appears in a compact drawer attached to its destination field.",
};

const field = (label: string, value: string) => (
  <section style={{ marginTop: 24 }}>
    <strong>{label}</strong>
    <div style={{ border: "1px solid #777", padding: 10, marginTop: 6 }}>Current {label.toLowerCase()}</div>
    <aside style={{ border: "1px solid #777", borderTop: 0, margin: "0 8px", padding: 10 }}>
      <small>✦ AI suggestion</small>
      <span style={{ float: "right" }}><button type="button">× Reject</button> <button type="button">✓ Accept</button></span>
      <p>{value}</p>
    </aside>
  </section>
);

export default function Proposal() {
  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 660, margin: "32px auto", padding: 24 }}>
      <header style={{ display: "flex", justifyContent: "space-between" }}><h1>Listing details</h1><button type="button">✦ Generate</button></header>
      {field("Title", "Retro Take A Hike Mountain Graphic Tee")}
      {field("Tags", "13 suggested tags")}
      {field("Description lead", "A short suggested opening for the listing description.")}
    </main>
  );
}
