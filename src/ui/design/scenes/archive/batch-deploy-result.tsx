// Retired: a separate result page cost a navigation to say what the review page could say in
// place. The applied state now lives on review itself - banner at the top, a success or failure
// marker on every item, failure detail in the drawer (batch-deploy-lofi/review-applied).
export const meta = {
  title: "Batch deployment — result page",
  viewport: "laptop",
  description:
    "Retired: the outcome now lands inline on the review page - one screen fewer in the flow.",
};
const page = {
  minHeight: "100vh",
  display: "flex",
  background: "#fff",
  color: "#111",
  fontFamily: "system-ui",
};
const sidebar = {
  width: 184,
  padding: 24,
  borderRight: "1px solid #aaa",
  display: "flex",
  flexDirection: "column" as const,
  gap: 18,
};
const main = { flex: 1, padding: "36px 48px" };
const card = { border: "1px solid #777", padding: 18, marginTop: 20, borderRadius: 0 };
const button = {
  cursor: "pointer",
  background: "#fff",
  color: "#111",
  border: "1px solid #555",
  borderRadius: 0,
  padding: "10px 14px",
  fontSize: 14,
};

export default function BatchResultWireframe() {
  return (
    <div style={page}>
      <style>{`.wf-button:hover { background:#e5e5e5 !important; } @media(max-width:720px){.wf-sidebar{display:none!important}.wf-main{padding:24px!important}}`}</style>
      <aside className="wf-sidebar" style={sidebar}>
        <strong>Listings</strong>
        <span>Dashboard</span>
        <strong>Listings</strong>
        <span>Mockup templates</span>
        <span style={{ marginTop: "auto", color: "#555" }}>Demo shop</span>
      </aside>
      <main className="wf-main" style={main}>
        <p style={{ color: "#555", margin: 0 }}>Listings / Deploy changes</p>
        <h1 style={{ margin: "6px 0", fontSize: 30 }}>Deployment result</h1>
        <p style={{ margin: 0, color: "#444" }}>
          The batch finished. Every listing is accounted for below.
        </p>
        <section style={card}>
          <strong>5 listings applied</strong>
          <p style={{ margin: "6px 0 0" }}>2 added · 3 changed</p>
        </section>
        <section style={{ ...card, borderColor: "#111" }}>
          <strong>1 listing needs attention</strong>
          <p style={{ margin: "6px 0 0" }}>
            Old logo tee was not removed because its Etsy listing could not be found. No other
            listing was rolled back.
          </p>
          <button type="button" className="wf-button" style={{ ...button, marginTop: 12 }}>
            Open Old logo tee →
          </button>
        </section>
        <section style={{ marginTop: 26 }}>
          <h2 style={{ fontSize: 18 }}>Completed</h2>
          {[
            "Night hike club — added as Etsy draft",
            "After rain trail — added as Etsy draft",
            "Mountain sunrise tee — updated",
            "Cedar trail shirt — updated",
            "Fjord mornings — updated",
          ].map((outcome) => (
            <p
              key={outcome}
              style={{ borderBottom: "1px solid #ccc", padding: "12px 0", margin: 0 }}
            >
              {outcome}
            </p>
          ))}
        </section>
        <button type="button" className="wf-button" style={{ ...button, marginTop: 28 }}>
          ← Back to listings
        </button>
      </main>
    </div>
  );
}
