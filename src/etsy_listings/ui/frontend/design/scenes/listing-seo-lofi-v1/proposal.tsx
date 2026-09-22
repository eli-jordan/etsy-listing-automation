export const meta = {
  title: "Listing SEO — proposal review · v1",
  viewport: "laptop",
  description: "Wireframe: compare current and proposed copy, then accept one field or all remaining fields.",
};

export default function Proposal() {
  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 980, margin: "32px auto", padding: 24 }}>
      <h1>Listing details</h1>
      <section style={{ border: "1px solid #777", padding: 20, marginTop: 24 }}>
        <h2>SEO proposal</h2>
        <button type="button">Apply all pending fields</button>
        <article style={{ borderTop: "1px solid #777", marginTop: 16, paddingTop: 16 }}>
          <h3>Title</h3><p>Current → Proposed title</p><button type="button">Accept title</button>
        </article>
        <article style={{ borderTop: "1px solid #777", marginTop: 16, paddingTop: 16 }}>
          <h3>Tags</h3><p>Current tags → 13 proposed tags</p><button type="button">Accept tags</button>
        </article>
        <article style={{ borderTop: "1px solid #777", marginTop: 16, paddingTop: 16 }}>
          <h3>Description lead</h3><p>Current lead → Proposed lead</p><button type="button">Accept lead</button>
        </article>
      </section>
    </main>
  );
}
