import { useState } from "react";

export const meta = {
  title: "Batch deployment — review (stages for the whole run) · retired · v1",
  viewport: "laptop",
  description:
    "Retired read B: one run-level strip counting listings per stage. The engine applies listing by listing, so this loses the per-listing answer and carries no progress during apply.",
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
type RunStage = { name: string; listings: string[] };

const changes: Change[] = [
  {
    id: "night-hike-club",
    title: "Night hike club · v1",
    copy: "new Printify product and Etsy draft",
    before: null,
    after: ["Title: Night Hike Club Tee", "Price: 349 NOK", "Images: 4 · all new", "Tags: 13"],
  },
  {
    id: "after-rain-trail",
    title: "After rain trail · v1",
    copy: "new Printify product and Etsy draft",
    before: null,
    after: ["Title: After Rain Trail Tee", "Price: 349 NOK", "Images: 3 · all new", "Tags: 11"],
  },
  {
    id: "mountain-sunrise-tee",
    title: "Mountain sunrise tee · v1",
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
    title: "Cedar trail shirt · v1",
    copy: "colours and images",
    before: ["Colours: 3", "Images: 4", "Price: 329 NOK"],
    after: ["Colours: 5 · 2 new", "Images: 6 · 2 new", "Price: 329 NOK · unchanged"],
  },
  {
    id: "fjord-mornings",
    title: "Fjord mornings · v1",
    copy: "description and tags",
    before: ["Description: 240 characters", "Tags: 8"],
    after: ["Description: 610 characters", "Tags: 13 · 5 new"],
  },
];

// The same five stages every listing walks, plus retract for the deletion —
// rolled up across the plan instead of shown per listing.
const runStages: RunStage[] = [
  {
    name: "Render mockups",
    listings: [
      "Night hike club · 4 scenes",
      "After rain trail · 3 scenes",
      "Mountain sunrise tee · 1 scene",
      "Cedar trail shirt · 2 scenes",
    ],
  },
  {
    name: "Printify product",
    listings: [
      "Night hike club · create",
      "After rain trail · create",
      "Mountain sunrise tee · title, price",
      "Cedar trail shirt · 2 colours",
      "Fjord mornings · description",
    ],
  },
  {
    name: "Publish to Etsy",
    listings: ["Night hike club · new draft", "After rain trail · new draft"],
  },
  {
    name: "Etsy listing",
    listings: [
      "Night hike club · all fields",
      "After rain trail · all fields",
      "Mountain sunrise tee · title, price",
      "Fjord mornings · description, tags",
    ],
  },
  {
    name: "Etsy images",
    listings: [
      "Night hike club · 4 uploads",
      "After rain trail · 3 uploads",
      "Mountain sunrise tee · 1 upload",
      "Cedar trail shirt · 2 uploads",
    ],
  },
  { name: "Remove from Etsy", listings: ["Old logo tee · retract 1284660391"] },
];

function Dot({ run }: { run: boolean }) {
  return (
    <span
      aria-hidden="true"
      style={{
        display: "inline-block",
        width: 10,
        height: 10,
        flex: "0 0 10px",
        border: "1px solid #111",
        background: run ? "#111" : "#fff",
      }}
    />
  );
}

function RunStrip({ stages }: { stages: RunStage[] }) {
  return (
    <section style={{ marginTop: 20 }}>
      <p style={{ margin: "0 0 8px", color: "#555" }}>What apply will do · across 6 listings</p>
      <div
        className="wf-steps"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
          border: "1px solid #999",
        }}
      >
        {stages.map((s, i) => (
          <div
            key={s.name}
            style={{ padding: 12, borderLeft: i === 0 ? "none" : "1px solid #999" }}
          >
            <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Dot run />
              <strong style={{ fontSize: 13 }}>{s.name}</strong>
            </span>
            <p style={{ margin: "6px 0 0", fontSize: 12.5, color: "#555" }}>
              {s.listings.length} listing{s.listings.length > 1 ? "s" : ""}
            </p>
            <details style={{ marginTop: 6, fontSize: 12 }}>
              <summary style={{ cursor: "pointer" }}>Which</summary>
              <ul style={{ margin: "4px 0 0", paddingLeft: 16, color: "#555" }}>
                {s.listings.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </details>
          </div>
        ))}
      </div>
    </section>
  );
}

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

export default function BatchReviewRunStagesWireframe() {
  const [index, setIndex] = useState(2);
  const [open, setOpen] = useState(true);
  const row = changes[index];
  const show = (i: number) => {
    setIndex(i);
    setOpen(true);
  };

  return (
    <div style={page}>
      <style>{`.wf-button:hover,.wf-row:hover { background:#e5e5e5 !important; } @media(max-width:900px){.wf-sidebar{display:none!important}.wf-main{padding:24px!important}.wf-diff{grid-template-columns:1fr!important}}`}</style>
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
        <RunStrip stages={runStages} />
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
            marginBottom: open ? 380 : 0,
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
        className="wf-sheet"
        aria-hidden={!open}
        style={{
          position: "fixed",
          left: 0,
          right: 0,
          bottom: 0,
          maxHeight: "60vh",
          background: "#fff",
          borderTop: "1px solid #777",
          display: "flex",
          flexDirection: "column" as const,
          transform: open ? "translateY(0)" : "translateY(100%)",
          transition: "transform 220ms ease",
        }}
      >
        <div style={{ display: "flex", justifyContent: "center", paddingTop: 10 }}>
          <span style={{ width: 52, height: 4, background: "#bbb" }} />
        </div>
        <header
          style={{
            padding: "14px 32px 18px",
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
            padding: "22px 32px 28px",
            display: "flex",
            flexDirection: "column" as const,
            gap: 14,
            overflow: "auto",
          }}
        >
          <p style={{ margin: 0, color: "#444" }}>
            The same evidence used in an individual deployment. Stages live in the run strip above,
            not here.
          </p>
          <div
            className="wf-diff"
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 16,
              alignItems: "start",
            }}
          >
            <Pane label="On Etsy now" lines={row.before} />
            <Pane label="After apply" lines={row.after} emphasis />
          </div>
        </div>
      </aside>
    </div>
  );
}
