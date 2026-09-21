export const meta = {
  title: "Listings — batch entry · v3",
  viewport: "laptop",
  description:
    "Wireframe: the Listings page carries pending batch work as colour-coded counts inside the Deploy changes button.",
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
const primary = {
  cursor: "pointer",
  background: "#111",
  color: "#fff",
  border: "1px solid #111",
  borderRadius: 0,
  padding: "10px 14px",
  fontSize: 14,
};
const count = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  minWidth: 20,
  height: 20,
  padding: "0 5px",
  color: "#111",
  fontSize: 12,
  fontWeight: 700,
  fontVariantNumeric: "tabular-nums" as const,
};
const preview = {
  position: "absolute" as const,
  top: "calc(100% + 8px)",
  right: 0,
  zIndex: 2,
  width: 310,
  padding: 14,
  background: "#fff",
  border: "1px solid #777",
  color: "#111",
  textAlign: "left" as const,
  boxShadow: "0 8px 24px rgba(0,0,0,.12)",
};

export default function ListingsWireframe() {
  return (
    <div className="wf-page" style={page}>
      <style>{`.wf-button:hover,.wf-row:hover { background:#e5e5e5 !important; } .wf-deploy-preview { opacity:0; transform:translateY(-4px); pointer-events:none; transition:opacity .14s ease,transform .14s ease; } .wf-deploy:hover .wf-deploy-preview,.wf-deploy:focus-within .wf-deploy-preview { opacity:1; transform:translateY(0); } @media(max-width:720px){.wf-sidebar{display:none!important}.wf-main{padding:24px!important}.wf-header{flex-wrap:wrap}.wf-actions{margin-left:0!important;width:100%}.wf-table{overflow-x:auto}}`}</style>
      <aside className="wf-sidebar" style={sidebar}>
        <strong>Listings</strong>
        <span>Dashboard</span>
        <strong>Listings</strong>
        <span>Mockup templates</span>
        <span style={{ marginTop: "auto", color: "#555" }}>Demo shop</span>
      </aside>
      <main className="wf-main" style={main}>
        <header className="wf-header" style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <h1 style={{ margin: 0, fontSize: 30 }}>Listings</h1>
          <span style={{ color: "#555" }}>12 shown</span>
          <div className="wf-actions" style={{ marginLeft: "auto", display: "flex", gap: 10 }}>
            <button
              type="button"
              className="wf-button"
              style={{ ...primary, background: "#fff", color: "#111" }}
            >
              + New listing
            </button>
            <div className="wf-deploy" style={{ position: "relative" }}>
              <button
                type="button"
                className="wf-button"
                data-goto="batch-deploy-lofi-v3/review-bottom-sheet"
                style={{
                  ...primary,
                  minWidth: 178,
                  display: "grid",
                  gridTemplateColumns: "1fr auto",
                  alignItems: "center",
                  columnGap: 10,
                  rowGap: 5,
                  textAlign: "left",
                }}
              >
                <strong>Deploy changes</strong>
                <span aria-hidden="true" style={{ gridRow: "1 / span 2", gridColumn: 2 }}>
                  →
                </span>
                <span
                  style={{ display: "inline-flex", gap: 5, gridColumn: 1 }}
                  aria-label="2 to add, 1 to delete, 3 to update"
                >
                  <span style={{ ...count, background: "#3fb950" }}>+2</span>
                  <span style={{ ...count, background: "#f85149" }}>−1</span>
                  <span style={{ ...count, background: "#58a6ff" }}>~3</span>
                </span>
              </button>
              <aside className="wf-deploy-preview" style={preview} aria-hidden="true">
                <strong>6 pending listing changes</strong>
                <div style={{ marginTop: 10, display: "grid", gap: 9, fontSize: 13 }}>
                  <div style={{ borderLeft: "5px solid #3fb950", paddingLeft: 9 }}>
                    <strong>Add 2</strong>
                    <div style={{ marginTop: 2, color: "#555" }}>
                      Night hike club · After rain trail
                    </div>
                  </div>
                  <div style={{ borderLeft: "5px solid #58a6ff", paddingLeft: 9 }}>
                    <strong>Edit 3</strong>
                    <div style={{ marginTop: 2, color: "#555" }}>
                      Mountain sunrise · Cedar trail · Fjord mornings
                    </div>
                  </div>
                  <div style={{ borderLeft: "5px solid #f85149", paddingLeft: 9 }}>
                    <strong>Remove 1</strong>
                    <div style={{ marginTop: 2, color: "#555" }}>Old logo tee</div>
                  </div>
                </div>
                <p
                  style={{
                    margin: "11px 0 0",
                    paddingTop: 10,
                    borderTop: "1px solid #ccc",
                    color: "#555",
                    fontSize: 12,
                  }}
                >
                  Open to generate a fresh plan across all listings.
                </p>
              </aside>
            </div>
          </div>
        </header>
        <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
          <input
            aria-label="Search listings"
            placeholder="Search listings…"
            style={{ border: "1px solid #777", padding: 10, width: 260, borderRadius: 0 }}
          />
          <button
            type="button"
            className="wf-button"
            style={{
              border: "1px solid #777",
              background: "#fff",
              padding: "10px 14px",
              cursor: "pointer",
              borderRadius: 0,
            }}
          >
            All statuses
          </button>
        </div>
        <div className="wf-table">
          <table
            style={{
              width: "100%",
              marginTop: 20,
              borderCollapse: "collapse",
              textAlign: "left",
              minWidth: 640,
            }}
          >
            <thead>
              <tr style={{ borderBottom: "1px solid #777" }}>
                <th style={{ padding: 12 }}>Listing</th>
                <th>Garment</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {[
                ["Mountain sunrise tee", "Comfort Colors 1717", "Dirty"],
                ["Night hike club", "Bella + Canvas 3001", "Draft"],
                ["Cedar trail shirt", "Comfort Colors 1717", "Pending delete"],
              ].map(([name, garment, status]) => (
                <tr key={name} className="wf-row" style={{ borderBottom: "1px solid #ccc" }}>
                  <td style={{ padding: 14 }}>
                    <strong>{name}</strong>
                  </td>
                  <td>{garment}</td>
                  <td>{status}</td>
                  <td>Open →</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>
    </div>
  );
}
