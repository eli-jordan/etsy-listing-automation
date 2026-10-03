export const meta = {
  title: "Listing SEO — generating · v1",
  viewport: "laptop",
  description: "Wireframe: a manual generation request is running from a snapshot of the listing’s current facts.",
};

export default function Generating() {
  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 980, margin: "32px auto", padding: 24 }}>
      <h1>Listing details</h1>
      <section style={{ border: "1px solid #777", padding: 20, marginTop: 24 }}>
        <h2>SEO assistant</h2>
        <p>Generating a proposal from the selected design and current brief…</p>
        <button type="button" disabled>Generating SEO</button>
        <p>Continue editing. If relevant facts change, this proposal will be marked stale.</p>
      </section>
    </main>
  );
}
