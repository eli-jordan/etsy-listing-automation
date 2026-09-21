import { useState } from "react";

// Retired: the owner rejected the big table. Six listings × five stages read as a spreadsheet —
// dense, hard to scan, and the cell labels ("Title, price", "2 uploads") repeated what the row
// already said. The live review page now lists listings plainly and keeps the stage detail in
// the bottom sheet, matching the individual deploy flow (batch-deploy-lofi/review-bottom-sheet).
export const meta = {
  title: "Batch deployment — review (stage matrix)",
  viewport: "laptop",
  description:
    "Retired: the stage matrix read as a spreadsheet - the plain listing list won, with stages per listing in the bottom sheet.",
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

// One pipeline, in the engine's order — `engine/stages/__init__.py`'s STAGES.
// There is no second set: `build_plan` walks these same five per listing, so
// the names are shared and only the state is per listing. A deleted listing
// walks `RetractStage()` alone (`lifecycle.walk`), hence its own lane below.
const pipeline = [
  { key: "render", label: "Render mockups" },
  { key: "printify_product", label: "Printify product" },
  { key: "publish", label: "Publish to Etsy" },
  { key: "etsy_listing", label: "Etsy listing" },
  { key: "etsy_media", label: "Etsy images" },
];

type StagePlan = { run: boolean; cell: string; why: string; actions: string[] };
type Change = {
  id: string;
  title: string;
  copy: string;
  group: "add" | "change";
  before: string[] | null;
  after: string[];
  stages: Record<string, StagePlan>;
};

const changes: Change[] = [
  {
    id: "night-hike-club",
    title: "Night hike club",
    copy: "new Printify product and Etsy draft",
    group: "add",
    before: null,
    after: ["Title: Night Hike Club Tee", "Price: 349 NOK", "Images: 4 · all new", "Tags: 13"],
    stages: {
      render: {
        run: true,
        cell: "4 scenes",
        why: "4 scenes missing",
        actions: [
          "Render front · black",
          "Render front · sand",
          "Render folded · black",
          "Render lifestyle · black",
        ],
      },
      printify_product: {
        run: true,
        cell: "Create",
        why: "Not created yet",
        actions: ["Create product from Unisex Heavy Cotton Tee", "Attach 4 mockups"],
      },
      publish: {
        run: true,
        cell: "New draft",
        why: "Not on Etsy yet",
        actions: ["Publish as draft, mint listing id"],
      },
      etsy_listing: {
        run: true,
        cell: "All fields",
        why: "New listing fields",
        actions: ["Set title, description, price", "Set 13 tags"],
      },
      etsy_media: {
        run: true,
        cell: "4 uploads",
        why: "4 images to upload",
        actions: ["Upload 4 images in order"],
      },
    },
  },
  {
    id: "after-rain-trail",
    title: "After rain trail",
    copy: "new Printify product and Etsy draft",
    group: "add",
    before: null,
    after: ["Title: After Rain Trail Tee", "Price: 349 NOK", "Images: 3 · all new", "Tags: 11"],
    stages: {
      render: {
        run: true,
        cell: "3 scenes",
        why: "3 scenes missing",
        actions: ["Render front · white", "Render front · moss", "Render folded · white"],
      },
      printify_product: {
        run: true,
        cell: "Create",
        why: "Not created yet",
        actions: ["Create product from Unisex Heavy Cotton Tee", "Attach 3 mockups"],
      },
      publish: {
        run: true,
        cell: "New draft",
        why: "Not on Etsy yet",
        actions: ["Publish as draft, mint listing id"],
      },
      etsy_listing: {
        run: true,
        cell: "All fields",
        why: "New listing fields",
        actions: ["Set title, description, price", "Set 11 tags"],
      },
      etsy_media: {
        run: true,
        cell: "3 uploads",
        why: "3 images to upload",
        actions: ["Upload 3 images in order"],
      },
    },
  },
  {
    id: "mountain-sunrise-tee",
    title: "Mountain sunrise tee",
    copy: "title, price, and images",
    group: "change",
    before: ["Title: Mountain Sunrise T-Shirt", "Price: 349 NOK", "Images: 5", "Tags: 12"],
    after: [
      "Title: Mountain Sunrise Hiking Tee",
      "Price: 379 NOK",
      "Images: 6 · 1 new",
      "Tags: 12 · unchanged",
    ],
    stages: {
      render: {
        run: true,
        cell: "1 scene",
        why: "1 scene stale",
        actions: ["Re-render lifestyle · charcoal"],
      },
      printify_product: {
        run: true,
        cell: "Title, price",
        why: "Price and title differ",
        actions: ["Update title to Mountain Sunrise Hiking Tee", "Set price 379 NOK"],
      },
      publish: { run: false, cell: "Published", why: "Already published", actions: [] },
      etsy_listing: {
        run: true,
        cell: "Title, price",
        why: "Title and price differ",
        actions: ["PATCH title, price"],
      },
      etsy_media: {
        run: true,
        cell: "1 upload",
        why: "1 image to add",
        actions: ["Upload lifestyle · charcoal", "Reorder to 6 images"],
      },
    },
  },
  {
    id: "cedar-trail-shirt",
    title: "Cedar trail shirt",
    copy: "colours and images",
    group: "change",
    before: ["Colours: 3", "Images: 4", "Price: 329 NOK"],
    after: ["Colours: 5 · 2 new", "Images: 6 · 2 new", "Price: 329 NOK · unchanged"],
    stages: {
      render: {
        run: true,
        cell: "2 scenes",
        why: "2 scenes missing",
        actions: ["Render front · forest", "Render front · clay"],
      },
      printify_product: {
        run: true,
        cell: "2 colours",
        why: "2 colours to enable",
        actions: ["Enable forest, clay", "Attach 2 mockups"],
      },
      publish: { run: false, cell: "Published", why: "Already published", actions: [] },
      etsy_listing: { run: false, cell: "No changes", why: "No changes", actions: [] },
      etsy_media: {
        run: true,
        cell: "2 uploads",
        why: "2 images to add",
        actions: ["Upload 2 images, keep order"],
      },
    },
  },
  {
    id: "fjord-mornings",
    title: "Fjord mornings",
    copy: "description and tags",
    group: "change",
    before: ["Description: 240 characters", "Tags: 8"],
    after: ["Description: 610 characters", "Tags: 13 · 5 new"],
    stages: {
      render: { run: false, cell: "No changes", why: "No changes", actions: [] },
      printify_product: {
        run: true,
        cell: "Description",
        why: "Description differs",
        actions: ["Update description"],
      },
      publish: { run: false, cell: "Published", why: "Already published", actions: [] },
      etsy_listing: {
        run: true,
        cell: "Description, tags",
        why: "Description and tags differ",
        actions: ["PATCH description", "Set 13 tags · 5 new"],
      },
      etsy_media: { run: false, cell: "No changes", why: "No changes", actions: [] },
    },
  },
];

const removal = {
  title: "Old logo tee",
  copy: "retract the remote listing, then remove its local files",
  stage: { key: "retract", label: "Remove from Etsy" },
  plan: {
    run: true,
    cell: "Retract 1284660391",
    why: "Marked for deletion",
    actions: ["Retract listing 1284660391", "Delete local files"],
  } as StagePlan,
};

const grid = {
  display: "grid",
  gridTemplateColumns: "minmax(210px, 1.3fr) repeat(5, 1fr)",
  alignItems: "stretch" as const,
};
const groups = { add: "Add to Etsy", change: "Change on Etsy" };

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

function Cell({ plan }: { plan: StagePlan }) {
  return (
    <span
      style={{
        display: "flex",
        alignItems: "center",
        gap: 7,
        padding: "12px 10px",
        borderLeft: "1px solid #ccc",
        background: plan.run ? "#fff" : "#f1f1f1",
        fontSize: 12.5,
        color: plan.run ? "#111" : "#555",
      }}
    >
      <Dot run={plan.run} />
      {plan.cell}
    </span>
  );
}

function ChangeRow({ row, active, onOpen }: { row: Change; active: boolean; onOpen: () => void }) {
  const runs = pipeline.filter((s) => row.stages[s.key].run).length;
  return (
    <button
      type="button"
      className="wf-row"
      onClick={onOpen}
      style={{
        ...button,
        ...grid,
        width: "100%",
        padding: 0,
        marginTop: 0,
        textAlign: "left" as const,
        border: "none",
        borderTop: "1px solid #999",
        outline: active ? "2px solid #111" : "none",
        outlineOffset: -2,
      }}
    >
      <span
        style={{ padding: "12px 12px", display: "flex", flexDirection: "column" as const, gap: 2 }}
      >
        <strong style={{ fontSize: 13.5 }}>{row.title}</strong>
        <span style={{ color: "#555", fontSize: 12 }}>
          {runs} of {pipeline.length} stages · {row.copy}
        </span>
      </span>
      {pipeline.map((s) => (
        <Cell key={s.key} plan={row.stages[s.key]} />
      ))}
    </button>
  );
}

function StageMatrix({ onOpen, openId }: { onOpen: (id: string) => void; openId: string | null }) {
  return (
    <section style={{ marginTop: 24 }}>
      <p style={{ margin: "0 0 8px", color: "#555" }}>
        What apply will do · the same five stages, listing by listing — open a row for its reasons,
        actions and diff
      </p>
      <div className="wf-matrix" style={{ border: "1px solid #999" }}>
        <div style={{ ...grid, background: "#f6f6f6" }}>
          <span style={{ padding: "12px 12px", fontSize: 12, color: "#555" }}>Listing</span>
          {pipeline.map((s) => {
            const count = changes.filter((c) => c.stages[s.key].run).length;
            return (
              <span
                key={s.key}
                style={{
                  padding: "12px 10px",
                  borderLeft: "1px solid #ccc",
                  display: "flex",
                  flexDirection: "column" as const,
                  gap: 2,
                }}
              >
                <strong style={{ fontSize: 12.5 }}>{s.label}</strong>
                <span style={{ fontSize: 12, color: "#555" }}>
                  {count} of {changes.length} listings
                </span>
              </span>
            );
          })}
        </div>
        {(["add", "change"] as const).map((group) => {
          const rows = changes.filter((c) => c.group === group);
          return (
            <div key={group}>
              <h2
                style={{
                  margin: 0,
                  padding: "8px 12px",
                  borderTop: "1px solid #999",
                  background: "#fafafa",
                  fontSize: 12,
                  fontWeight: 400,
                  color: "#555",
                }}
              >
                {groups[group]} · {rows.length}
              </h2>
              {rows.map((row) => (
                <ChangeRow
                  key={row.id}
                  row={row}
                  active={openId === row.id}
                  onOpen={() => onOpen(row.id)}
                />
              ))}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function RemovalLane() {
  return (
    <section style={{ marginTop: 24 }}>
      <p style={{ margin: "0 0 8px", color: "#555" }}>
        Remove from Etsy · 1 — a deletion walks one stage, not the pipeline
      </p>
      <div
        style={{
          border: "1px solid #999",
          display: "grid",
          gridTemplateColumns: "minmax(210px, 1.3fr) 1fr",
        }}
      >
        <span style={{ padding: "12px 12px", fontSize: 12, color: "#555", background: "#f6f6f6" }}>
          Listing
        </span>
        <span
          style={{
            padding: "12px 10px",
            borderLeft: "1px solid #ccc",
            background: "#f6f6f6",
            display: "flex",
            flexDirection: "column" as const,
            gap: 2,
          }}
        >
          <strong style={{ fontSize: 12.5 }}>{removal.stage.label}</strong>
          <span style={{ fontSize: 12, color: "#555" }}>1 of 1 listing</span>
        </span>
        <span
          style={{
            padding: "12px 12px",
            borderTop: "1px solid #999",
            display: "flex",
            flexDirection: "column" as const,
            gap: 2,
          }}
        >
          <strong style={{ fontSize: 13.5 }}>{removal.title}</strong>
          <span style={{ color: "#555", fontSize: 12 }}>1 of 1 stage · {removal.copy}</span>
        </span>
        <Cell plan={removal.plan} />
      </div>
    </section>
  );
}

function StepStrip({ row }: { row: Change }) {
  const runs = pipeline.filter((s) => row.stages[s.key].run).length;
  return (
    <section>
      <p style={{ margin: "0 0 8px", color: "#555" }}>
        What apply will do · {runs} of {pipeline.length} stages
      </p>
      <div
        className="wf-steps"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
          border: "1px solid #999",
        }}
      >
        {pipeline.map((s, i) => {
          const plan = row.stages[s.key];
          return (
            <div
              key={s.key}
              style={{
                padding: 12,
                borderLeft: i === 0 ? "none" : "1px solid #999",
                background: plan.run ? "#fff" : "#f1f1f1",
              }}
            >
              <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Dot run={plan.run} />
                <strong style={{ fontSize: 13, color: plan.run ? "#111" : "#555" }}>
                  {s.label}
                </strong>
              </span>
              <p style={{ margin: "6px 0 0", fontSize: 12.5, color: "#555" }}>{plan.why}</p>
              {plan.run && plan.actions.length > 0 && (
                <details style={{ marginTop: 6, fontSize: 12 }}>
                  <summary style={{ cursor: "pointer" }}>
                    {plan.actions.length} action{plan.actions.length > 1 ? "s" : ""}
                  </summary>
                  <ul style={{ margin: "4px 0 0", paddingLeft: 16, color: "#555" }}>
                    {plan.actions.map((a) => (
                      <li key={a}>{a}</li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          );
        })}
      </div>
    </section>
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

export default function BatchReviewStageMatrixRetired() {
  const [index, setIndex] = useState(2);
  const [open, setOpen] = useState(false);
  const row = changes[index];
  const show = (id: string) => {
    setIndex(changes.findIndex((c) => c.id === id));
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
            Apply takes one listing at a time, top to bottom, and walks the same five stages —
            skipping the ones that have nothing to do.
          </p>
        </section>
        <StageMatrix onOpen={show} openId={open ? row.id : null} />
        <RemovalLane />
        <footer
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            borderTop: "1px solid #777",
            marginTop: 30,
            paddingTop: 18,
            marginBottom: open ? 470 : 0,
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
            <p style={{ margin: 0, color: "#555" }}>{groups[row.group]}</p>
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
          <StepStrip row={row} />
          <Diff row={row} />
        </div>
      </aside>
    </div>
  );
}
