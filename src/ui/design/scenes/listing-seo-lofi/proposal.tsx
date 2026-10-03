export const meta = {
  title: "Listing SEO — ranked choices",
  viewport: "laptop",
  description: "Wireframe: three one-click title and lead choices plus a ranked pool of 20 selectable tags.",
};

const choiceField = (label: string) => (
  <section style={{ marginTop: 22 }}>
    <strong>{label}</strong>
    <div style={{ border: "1px solid #777", padding: 9, marginTop: 5 }}>Current {label.toLowerCase()}</div>
    <aside style={{ border: "1px solid #777", borderTop: 0, margin: "0 7px", padding: 9 }}>
      <small>✦ Choose one</small><button style={{ float: "right" }} type="button">× Reject all</button>
      {[1, 2, 3].map((number) => <button key={number} style={{ display: "block", width: "100%", marginTop: 5, textAlign: "left" }} type="button">{number}. Suggested {label.toLowerCase()} {number}</button>)}
    </aside>
  </section>
);

export default function Proposal() {
  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 660, margin: "32px auto", padding: 24 }}>
      <header style={{ display: "flex", justifyContent: "space-between" }}><h1>Listing details</h1><button type="button">✦ AI Mode</button></header>
      {choiceField("Title")}
      <section style={{ marginTop: 22 }}><strong>Tags</strong><div style={{ border: "1px solid #777", padding: 9, marginTop: 5 }}>Selected tags</div><aside style={{ border: "1px solid #777", borderTop: 0, margin: "0 7px", padding: 9 }}><small>20 ranked suggestions</small><button style={{ float: "right" }} type="button">✓ Accept best 13</button><p>Best 13: selectable tag chips</p><p>More options: 7 selectable tag chips</p></aside></section>
      {choiceField("Description lead")}
    </main>
  );
}
