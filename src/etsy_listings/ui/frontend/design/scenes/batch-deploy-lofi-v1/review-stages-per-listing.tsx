import { useState } from "react";

// Retired read A, kept as history: the frame the "per item or per plan?" thread sat on.
// The engine has one STAGES list walked per listing. The live review frame keeps that strip
// but shows it for ONE listing at a time, in the bottom sheet - see review-bottom-sheet.
export const meta = {
  title: "Batch deployment — review (stages per listing) · retired · v1",
  viewport: "laptop",
  description:
    "Retired read A: a full step strip per listing, all six at once. The live frame shows the same strip for one listing at a time, in the bottom sheet.",
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

type Stage = { name: string; run: boolean; why: string; actions: string[] };
type Change = {
  id: string;
  title: string;
  copy: string;
  before: string[] | null;
  after: string[];
  stages: Stage[];
};

const changes: Change[] = [
  {
    id: "night-hike-club",
    title: "Night hike club · v1",
    copy: "new Printify product and Etsy draft",
    before: null,
    after: ["Title: Night Hike Club Tee", "Price: 349 NOK", "Images: 4 · all new", "Tags: 13"],
    stages: [
      {
        name: "Render mockups",
        run: true,
        why: "4 scenes missing",
        actions: [
          "Render front · black",
          "Render front · sand",
          "Render folded · black",
          "Render lifestyle · black",
        ],
      },
      {
        name: "Printify product",
        run: true,
        why: "Not created yet",
        actions: ["Create product from Unisex Heavy Cotton Tee", "Attach 4 mockups"],
      },
      {
        name: "Publish to Etsy",
        run: true,
        why: "Not on Etsy yet",
        actions: ["Publish as draft, mint listing id"],
      },
      {
        name: "Etsy listing",
        run: true,
        why: "New listing fields",
        actions: ["Set title, description, price", "Set 13 tags"],
      },
      {
        name: "Etsy images",
        run: true,
        why: "4 images to upload",
        actions: ["Upload 4 images in order"],
      },
    ],
  },
  {
    id: "after-rain-trail",
    title: "After rain trail · v1",
    copy: "new Printify product and Etsy draft",
    before: null,
    after: ["Title: After Rain Trail Tee", "Price: 349 NOK", "Images: 3 · all new", "Tags: 11"],
    stages: [
      {
        name: "Render mockups",
        run: true,
        why: "3 scenes missing",
        actions: ["Render front · white", "Render front · moss", "Render folded · white"],
      },
      {
        name: "Printify product",
        run: true,
        why: "Not created yet",
        actions: ["Create product from Unisex Heavy Cotton Tee", "Attach 3 mockups"],
      },
      {
        name: "Publish to Etsy",
        run: true,
        why: "Not on Etsy yet",
        actions: ["Publish as draft, mint listing id"],
      },
      {
        name: "Etsy listing",
        run: true,
        why: "New listing fields",
        actions: ["Set title, description, price", "Set 11 tags"],
      },
      {
        name: "Etsy images",
        run: true,
        why: "3 images to upload",
        actions: ["Upload 3 images in order"],
      },
    ],
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
    stages: [
      {
        name: "Render mockups",
        run: true,
        why: "1 scene stale",
        actions: ["Re-render lifestyle · charcoal"],
      },
      {
        name: "Printify product",
        run: true,
        why: "Price and title differ",
        actions: ["Update title to Mountain Sunrise Hiking Tee", "Set price 379 NOK"],
      },
      { name: "Publish to Etsy", run: false, why: "Already published", actions: [] },
      {
        name: "Etsy listing",
        run: true,
        why: "Title and price differ",
        actions: ["PATCH title, price"],
      },
      {
        name: "Etsy images",
        run: true,
        why: "1 image to add",
        actions: ["Upload lifestyle · charcoal", "Reorder to 6 images"],
      },
    ],
  },
  {
    id: "cedar-trail-shirt",
    title: "Cedar trail shirt · v1",
    copy: "colours and images",
    before: ["Colours: 3", "Images: 4", "Price: 329 NOK"],
    after: ["Colours: 5 · 2 new", "Images: 6 · 2 new", "Price: 329 NOK · unchanged"],
    stages: [
      {
        name: "Render mockups",
        run: true,
        why: "2 scenes missing",
        actions: ["Render front · forest", "Render front · clay"],
      },
      {
        name: "Printify product",
        run: true,
        why: "2 colours to enable",
        actions: ["Enable forest, clay", "Attach 2 mockups"],
      },
      { name: "Publish to Etsy", run: false, why: "Already published", actions: [] },
      { name: "Etsy listing", run: false, why: "No changes", actions: [] },
      {
        name: "Etsy images",
        run: true,
        why: "2 images to add",
        actions: ["Upload 2 images, keep order"],
      },
    ],
  },
  {
    id: "fjord-mornings",
    title: "Fjord mornings · v1",
    copy: "description and tags",
    before: ["Description: 240 characters", "Tags: 8"],
    after: ["Description: 610 characters", "Tags: 13 · 5 new"],
    stages: [
      { name: "Render mockups", run: false, why: "No changes", actions: [] },
      {
        name: "Printify product",
        run: true,
        why: "Description differs",
        actions: ["Update description"],
      },
      { name: "Publish to Etsy", run: false, why: "Already published", actions: [] },
      {
        name: "Etsy listing",
        run: true,
        why: "Description and tags differ",
        actions: ["PATCH description", "Set 13 tags · 5 new"],
      },
      { name: "Etsy images", run: false, why: "No changes", actions: [] },
    ],
  },
];

const removalStages: Stage[] = [
  {
    name: "Remove from Etsy",
    run: true,
    why: "Marked for deletion",
    actions: ["Retract listing 1284660391", "Delete local files"],
  },
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

function StageTrail({ stages }: { stages: Stage[] }) {
  const runs = stages.filter((s) => s.run).length;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        color: "#555",
        whiteSpace: "nowrap" as const,
      }}
    >
      <span style={{ display: "inline-flex", gap: 4 }}>
        {stages.map((s) => (
          <Dot key={s.name} run={s.run} />
        ))}
      </span>
      {runs} of {stages.length} stages
    </span>
  );
}

function StepStrip({ stages, heading }: { stages: Stage[]; heading: string }) {
  return (
    <section>
      <p style={{ margin: "0 0 8px", color: "#555" }}>{heading}</p>
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
            style={{
              padding: 12,
              borderLeft: i === 0 ? "none" : "1px solid #999",
              background: s.run ? "#fff" : "#f1f1f1",
            }}
          >
            <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Dot run={s.run} />
              <strong style={{ fontSize: 13, color: s.run ? "#111" : "#555" }}>{s.name}</strong>
            </span>
            <p style={{ margin: "6px 0 0", fontSize: 12.5, color: "#555" }}>{s.why}</p>
            {s.run && s.actions.length > 0 && (
              <details style={{ marginTop: 6, fontSize: 12 }}>
                <summary style={{ cursor: "pointer" }}>
                  {s.actions.length} action{s.actions.length > 1 ? "s" : ""}
                </summary>
                <ul style={{ margin: "4px 0 0", paddingLeft: 16, color: "#555" }}>
                  {s.actions.map((a) => (
                    <li key={a}>{a}</li>
                  ))}
                </ul>
              </details>
            )}
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
      <span style={{ display: "inline-flex", alignItems: "center", gap: 18 }}>
        <StageTrail stages={row.stages} />
        <span style={{ color: "#555", whiteSpace: "nowrap" as const }}>View changes →</span>
      </span>
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

export default function BatchReviewStagesPerListingRetired() {
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
          <p style={{ margin: "6px 0 0", color: "#555" }}>
            Apply works one listing at a time, running that listing's own stages in order.
          </p>
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
          <p style={{ margin: "8px 0 14px" }}>
            <strong>Old logo tee</strong> — retract the remote listing, then remove its local files.
          </p>
          <StepStrip stages={removalStages} heading="What apply will do · 1 stage" />
        </section>
        <footer
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            borderTop: "1px solid #777",
            marginTop: 30,
            paddingTop: 18,
            marginBottom: open ? 480 : 0,
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
          maxHeight: "68vh",
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
            gap: 18,
            overflow: "auto",
          }}
        >
          <StepStrip
            stages={row.stages}
            heading={`What apply will do · ${row.stages.filter((s) => s.run).length} of ${row.stages.length} stages`}
          />
          <Diff row={row} />
        </div>
      </aside>
    </div>
  );
}
