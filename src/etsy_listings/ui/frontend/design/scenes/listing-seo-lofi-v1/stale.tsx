export const meta = {
  title: "Listing SEO — stale proposal · v1",
  viewport: "laptop",
  description: "Wireframe: a pending proposal is retained but cannot be applied after relevant listing facts change.",
};

export default function Stale() {
  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 980, margin: "32px auto", padding: 24 }}>
      <h1>Listing details</h1>
      <section style={{ border: "1px solid #777", padding: 20, marginTop: 24 }}>
        <h2>SEO proposal is stale</h2>
        <p>The design or listing brief changed after this proposal was generated.</p>
        <button type="button">Regenerate SEO</button>
        <p>The saved title, tags, and description lead are unchanged.</p>
      </section>
    </main>
  );
}
