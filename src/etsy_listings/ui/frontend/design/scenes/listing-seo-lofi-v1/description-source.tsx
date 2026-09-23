export const meta = {
  title: "Listing SEO — description source · v1",
  viewport: "laptop",
  description: "Wireframe: choose an approved common-copy body or write listing-specific inline body copy.",
};

export default function DescriptionSource() {
  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 980, margin: "32px auto", padding: 24 }}>
      <h1>Listing details</h1>
      <section style={{ border: "1px solid #777", padding: 20, marginTop: 24 }}>
        <h2>Description body</h2>
        <p>Choose a reusable body or add listing-specific copy.</p>
        <select defaultValue="comfort-colors-care.md" aria-label="Description body source">
          <option value="comfort-colors-care.md">Comfort Colors care and fit</option>
          <option value="inline">Write inline body</option>
        </select>
        <p>Selected file: common-copy/comfort-colors-care.md</p>
      </section>
    </main>
  );
}
