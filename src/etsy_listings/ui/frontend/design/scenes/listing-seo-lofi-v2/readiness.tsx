export const meta = {
  title: "Listing SEO — readiness · v2",
  viewport: "laptop",
  description: "Wireframe: a subtle disabled sparkle action explains its missing inputs on hover.",
};

export default function Readiness() {
  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 660, margin: "32px auto", padding: 24 }}>
      <header style={{ display: "flex", justifyContent: "space-between" }}>
        <div><h1>Listing details</h1><p>Copy shown to shoppers on Etsy.</p></div>
        <button type="button" disabled title="Select a design and add a listing brief first.">✦ Generate</button>
      </header>
      <p style={{ border: "1px solid #777", padding: 12, marginTop: 28 }}>Title</p>
      <p style={{ border: "1px solid #777", padding: 12 }}>Tags</p>
      <p style={{ border: "1px solid #777", padding: 12 }}>Description lead</p>
    </main>
  );
}
