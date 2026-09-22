export const meta = {
  title: "Listing SEO — stale choices",
  viewport: "laptop",
  description: "Wireframe: stale choices remain dismissible but cannot be selected until AI Mode runs again.",
};

export default function Stale() {
  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 660, margin: "32px auto", padding: 24 }}>
      <header style={{ display: "flex", justifyContent: "space-between" }}><h1>Listing details</h1><button type="button">✦ AI Mode</button></header>
      <section style={{ marginTop: 28 }}><strong>Title</strong><div style={{ border: "1px solid #777", padding: 9, marginTop: 5 }}>Take A Hike Mountain Tee</div><aside style={{ border: "1px solid #999", borderTop: 0, margin: "0 7px", padding: 9 }}><small>Suggestions are out of date</small><button style={{ float: "right" }} type="button">× Reject all</button>{[1, 2, 3].map((number) => <button disabled key={number} style={{ display: "block", width: "100%", marginTop: 5 }} type="button">Suggested title {number}</button>)}</aside></section>
    </main>
  );
}
