import { useState } from "react";

// Retired: the bottom drawer won. A 780px right-hand drawer covered the list it was meant to
// explain, so the before/after lost its context; the bottom sheet keeps the row in view while
// the evidence rises under it (batch-deploy-lofi/review-bottom-sheet).
export const meta = {
  title: "Batch deployment — review (side drawer)",
  viewport: "laptop",
  description:
    "Retired: the bottom drawer won - a right-hand drawer hid the list of changes it was explaining.",
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
const pane = { border: "1px solid #999", padding: 14 };

type Change = { id: string; title: string; copy: string; before: string[] | null; after: string[] };

const changes: Change[] = [
  {
    id: "night-hike-club",
    title: "Night hike club",
    copy: "new Printify product and Etsy draft",
    before: null,
    after: ["Title: Night Hike Club Tee", "Price: 349 NOK", "Images: 4 · all new", "Tags: 13"],
  },
  {
    id: "after-rain-trail",
    title: "After rain trail",
    copy: "new Printify product and Etsy draft",
    before: null,
    after: ["Title: After Rain Trail Tee", "Price: 349 NOK", "Images: 3 · all new", "Tags: 11"],
  },
  {
    id: "mountain-sunrise-tee",
    title: "Mountain sunrise tee",
    copy: "title, price, and images",
    before: ["Title: Mountain Sunrise T-Shirt", "Price: 349 NOK", "Images: 5", "Tags: 12"],
    after: [
      "Title: Mountain Sunrise Hiking Tee",
      "Price: 379 NOK",
      "Images: 6 · 1 new",
      "Tags: 12 · unchanged",
    ],
  },
  {
    id: "cedar-trail-shirt",
    title: "Cedar trail shirt",
    copy: "colours and images",
    before: ["Colours: 3", "Images: 4", "Price: 329 NOK"],
    after: ["Colours: 5 · 2 new", "Images: 6 · 2 new", "Price: 329 NOK · unchanged"],
  },
  {
    id: "fjord-mornings",
    title: "Fjord mornings",
    copy: "description and tags",
    before: ["Description: 240 characters", "Tags: 8"],
    after: ["Description: 610 characters", "Tags: 13 · 5 new"],
  },
];

function ChangeRow({ row, active, onOpen }: { row: Change; active: boolean; onOpen: () => void }) {
  return (
    <button
      type="button"
      className="wf-row"
      data-testid={`change-row-${row.id}`}
      onClick={onOpen}
      style={{
        ...button,
        width: "100%",
        marginTop: 10,
        padding: 14,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 16,
        textAlign: "left" as const,
        border: active ? "1px solid #111" : "1px solid #999",
      }}
    >
      <span>
        <strong>{row.title}</strong> <span style={{ color: "#555" }}>— {row.copy}</span>
      </span>
      <span style={{ color: "#555", whiteSpace: "nowrap" as const }}>View changes →</span>
    </button>
  );
}

function Pane({
  label,
  lines,
  emphasis,
}: {
  label: string;
  lines: string[] | null;
  emphasis?: boolean;
}) {
  return (
    <section style={{ ...pane, border: emphasis ? "1px solid #111" : pane.border }}>
      <strong>{label}</strong>
      {lines ? (
        lines.map((line) => (
          <p key={line} style={{ margin: "8px 0 0" }}>
            {line}
          </p>
        ))
      ) : (
        <p style={{ margin: "8px 0 0", color: "#555" }}>
          Not on Etsy yet — this listing will be created.
        </p>
      )}
    </section>
  );
}

function Diff({ row }: { row: Change }) {
  return (
    <div
      className="wf-diff"
      style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, alignItems: "start" }}
    >
      <Pane label="On Etsy now" lines={row.before} />
      <Pane label="After apply" lines={row.after} emphasis />
    </div>
  );
}

export default function BatchReviewSideDrawerWireframe() {
  const [index, setIndex] = useState(2);
  const [open, setOpen] = useState(true);
  const row = changes[index];
  const show = (i: number) => {
    setIndex(i);
    setOpen(true);
  };

  return (
    <div style={page}>
      <style>{`.wf-button:hover,.wf-row:hover { background:#e5e5e5 !important; } @media(max-width:900px){.wf-sidebar{display:none!important}.wf-main{padding:24px!important}.wf-drawer{width:100%!important}.wf-diff{grid-template-columns:1fr!important}}`}</style>
      <aside className="wf-sidebar" style={sidebar}>
        <strong>Listings</strong>
        <span>Dashboard</span>
        <strong>Listings</strong>
        <span>Mockup templates</span>
        <span style={{ marginTop: "auto", color: "#555" }}>Demo shop</span>
      </aside>
      <main className="wf-main" style={main}>
        <button type="button" className="wf-button" style={button}>
          ← Back to listings
        </button>
        <header style={{ marginTop: 22 }}>
          <p style={{ color: "#555", margin: 0 }}>Listings / Deploy changes</p>
          <h1 style={{ margin: "6px 0", fontSize: 30 }}>Review all changes</h1>
          <p style={{ margin: 0, color: "#444" }}>
            This plan covers every listing in your workspace. Nothing has been changed yet.
          </p>
        </header>
        <section style={card}>
          <strong>6 listings affected</strong>
          <p style={{ margin: "6px 0 0" }}>2 to add · 3 to change · 1 marked for deletion</p>
        </section>
        <section style={{ marginTop: 26 }}>
          <h2 style={{ fontSize: 18 }}>Add to Etsy · 2</h2>
          {changes.slice(0, 2).map((c, i) => (
            <ChangeRow key={c.id} row={c} active={open && index === i} onOpen={() => show(i)} />
          ))}
        </section>
        <section style={{ marginTop: 26 }}>
          <h2 style={{ fontSize: 18 }}>Change on Etsy · 3</h2>
          {changes.slice(2).map((c, i) => (
            <ChangeRow
              key={c.id}
              row={c}
              active={open && index === i + 2}
              onOpen={() => show(i + 2)}
            />
          ))}
        </section>
        <section style={{ ...card, marginTop: 26 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>Remove from Etsy · 1</h2>
          <p style={{ margin: "8px 0 0" }}>
            <strong>Old logo tee</strong> — retract the remote listing, then remove its local files.
          </p>
        </section>
        <footer
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            borderTop: "1px solid #777",
            marginTop: 30,
            paddingTop: 18,
          }}
        >
          <span>6 listings reviewed</span>
          <button
            type="button"
            className="wf-button"
            style={{ ...button, background: "#111", color: "#fff" }}
          >
            Apply 6 changes →
          </button>
        </footer>
      </main>

      <div
        onClick={() => setOpen(false)}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(17,17,17,0.14)",
          opacity: open ? 1 : 0,
          pointerEvents: open ? "auto" : "none",
          transition: "opacity 180ms ease",
        }}
      />
      <aside
        className="wf-drawer"
        aria-hidden={!open}
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          bottom: 0,
          width: 780,
          background: "#fff",
          borderLeft: "1px solid #777",
          display: "flex",
          flexDirection: "column" as const,
          transform: open ? "translateX(0)" : "translateX(100%)",
          transition: "transform 220ms ease",
        }}
      >
        <header
          style={{
            padding: "22px 24px",
            borderBottom: "1px solid #999",
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 16,
          }}
        >
          <div>
            <p style={{ margin: 0, color: "#555" }}>
              {index < 2 ? "Add to Etsy" : "Change on Etsy"}
            </p>
            <h2 style={{ margin: "4px 0 0", fontSize: 22 }}>{row.title}</h2>
            <p style={{ margin: "4px 0 0", color: "#444" }}>{row.copy}</p>
          </div>
          <button
            type="button"
            className="wf-button"
            aria-label="Close"
            onClick={() => setOpen(false)}
            style={{ ...button, padding: "6px 10px" }}
          >
            ✕
          </button>
        </header>
        <div
          style={{
            padding: 24,
            display: "flex",
            flexDirection: "column" as const,
            gap: 14,
            overflow: "auto",
          }}
        >
          <p style={{ margin: 0, color: "#444" }}>
            The same evidence used in an individual deployment.
          </p>
          <Diff row={row} />
        </div>
      </aside>
    </div>
  );
}
