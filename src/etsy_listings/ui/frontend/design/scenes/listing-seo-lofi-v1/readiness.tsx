export const meta = {
  title: "Listing SEO — readiness · v1",
  viewport: "laptop",
  description: "Wireframe: the unavailable SEO action explains its missing inputs on hover.",
};

export default function Readiness() {
  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 980, margin: "32px auto", padding: 24 }}>
      <h1>Listing details</h1>
      <section style={{ border: "1px solid #777", padding: 20, marginTop: 24 }}>
        <h2>SEO assistant</h2>
        <p>Generate a reviewable title, 13 tags, and description lead from this listing.</p>
        <button type="button" disabled title="Select a design and add a listing brief to generate SEO copy.">
          Generate SEO
        </button>
      </section>
      <section style={{ border: "1px solid #777", padding: 20, marginTop: 24 }}>
        <h2>Listing copy</h2>
        <p>Title · Tags · Description lead · Description body source</p>
      </section>
    </main>
  );
}
