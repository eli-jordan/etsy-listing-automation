import { useState } from "react";

export const meta = {
  title: "Batch deployment — review (applied) · v1",
  viewport: "laptop",
  description:
    "Wireframe: the outcome lands on the plan review page itself — a banner at the top, a success or failure marker on every item. No separate result page.",
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
const marker = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  width: 20,
  height: 20,
  flex: "0 0 20px",
  color: "#fff",
  fontSize: 12,
  lineHeight: 1,
};
const ok = "#3fb950";
const bad = "#f85149";

type Change = {
  id: string;
  title: string;
  copy: string;
  group: "add" | "change" | "remove";
  before: string[] | null;
  after: string[] | null;
  done: boolean;
  outcome: string;
  note?: string;
};

const changes: Change[] = [
  {
    id: "night-hike-club",
    title: "Night hike club · v1",
    copy: "new Printify product and Etsy draft",
    group: "add",
    before: null,
    after: ["Title: Night Hike Club Tee", "Price: 349 NOK", "Images: 4 · all new", "Tags: 13"],
    done: true,
    outcome: "Added as Etsy draft",
  },
  {
    id: "after-rain-trail",
    title: "After rain trail · v1",
    copy: "new Printify product and Etsy draft",
    group: "add",
    before: null,
    after: ["Title: After Rain Trail Tee", "Price: 349 NOK", "Images: 3 · all new", "Tags: 11"],
    done: true,
    outcome: "Added as Etsy draft",
  },
  {
    id: "mountain-sunrise-tee",
    title: "Mountain sunrise tee · v1",
    copy: "title, price, and images",
    group: "change",
    before: ["Title: Mountain Sunrise T-Shirt", "Price: 349 NOK", "Images: 5", "Tags: 12"],
    after: [
      "Title: Mountain Sunrise Hiking Tee",
      "Price: 379 NOK",
      "Images: 6 · 1 new",
      "Tags: 12 · unchanged",
    ],
    done: true,
    outcome: "Updated",
  },
  {
    id: "cedar-trail-shirt",
    title: "Cedar trail shirt · v1",
    copy: "colours and images",
    group: "change",
    before: ["Colours: 3", "Images: 4", "Price: 329 NOK"],
    after: ["Colours: 5 · 2 new", "Images: 6 · 2 new", "Price: 329 NOK · unchanged"],
    done: true,
    outcome: "Updated",
  },
  {
    id: "fjord-mornings",
    title: "Fjord mornings · v1",
    copy: "description and tags",
    group: "change",
    before: ["Description: 240 characters", "Tags: 8"],
    after: ["Description: 610 characters", "Tags: 13 · 5 new"],
    done: true,
    outcome: "Updated",
  },
  {
    id: "old-logo-tee",
    title: "Old logo tee · v1",
    copy: "retract the remote listing, then remove its local files",
    group: "remove",
    before: ["Listing id: 1284660391", "Images: 5", "Price: 299 NOK"],
    after: null,
    done: false,
    outcome: "Not removed",
    note: "Etsy could not find this listing, so nothing was retracted. The local files are untouched and no other listing was rolled back.",
  },
];

const groups = { add: "Add to Etsy", change: "Change on Etsy", remove: "Remove from Etsy" };

function Marker({ done }: { done: boolean }) {
  return (
    <span aria-hidden="true" style={{ ...marker, background: done ? ok : bad }}>
      {done ? "✓" : "✕"}
    </span>
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
        border: active || !row.done ? "1px solid #111" : "1px solid #999",
      }}
    >
      <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Marker done={row.done} />
        <span>
          <strong>{row.title}</strong> <span style={{ color: "#555" }}>— {row.copy}</span>
        </span>
      </span>
      <span style={{ color: row.done ? "#555" : "#111", whiteSpace: "nowrap" as const }}>
        {row.outcome} →
      </span>
    </button>
  );
}

function Pane({
  label,
  lines,
  empty,
  emphasis,
}: {
  label: string;
  lines: string[] | null;
  empty: string;
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
        <p style={{ margin: "8px 0 0", color: "#555" }}>{empty}</p>
      )}
    </section>
  );
}

export default function BatchReviewAppliedWireframe() {
  const [index, setIndex] = useState(5);
  const [open, setOpen] = useState(false);
  const row = changes[index];
  const show = (i: number) => {
    setIndex(i);
    setOpen(true);
  };
  const applied = changes.filter((c) => c.done).length;
  const failed = changes.length - applied;

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
        <button
          type="button"
          className="wf-button"
          data-goto="batch-deploy-lofi-v1/listings"
          style={button}
        >
          ← Back to listings
        </button>
        <header style={{ marginTop: 22 }}>
          <p style={{ color: "#555", margin: 0 }}>Listings / Deploy changes</p>
          <h1 style={{ margin: "6px 0", fontSize: 30 }}>Review all changes</h1>
          <p style={{ margin: 0, color: "#444" }}>
            Applied a moment ago. Every listing below carries its outcome.
          </p>
        </header>
        <section
          data-testid="apply-banner"
          style={{
            ...card,
            borderColor: "#111",
            display: "flex",
            alignItems: "flex-start",
            gap: 12,
          }}
        >
          <Marker done={failed === 0} />
          <div style={{ flex: 1 }}>
            <strong>
              {applied} of {changes.length} applied · {failed} needs attention
            </strong>
            <p style={{ margin: "6px 0 0" }}>
              2 added · 3 changed. Old logo tee was not removed; nothing else was rolled back.
            </p>
          </div>
          <button
            type="button"
            className="wf-button"
            onClick={() => show(5)}
            style={{ ...button, whiteSpace: "nowrap" as const }}
          >
            Fix Old logo tee →
          </button>
        </section>
        {(["add", "change", "remove"] as const).map((group) => {
          const rows = changes.filter((c) => c.group === group);
          return (
            <section key={group} style={{ marginTop: 26 }}>
              <h2 style={{ fontSize: 18 }}>
                {groups[group]} · {rows.length}
              </h2>
              {rows.map((c) => (
                <ChangeRow
                  key={c.id}
                  row={c}
                  active={open && changes[index].id === c.id}
                  onOpen={() => show(changes.indexOf(c))}
                />
              ))}
            </section>
          );
        })}
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
          <span style={{ color: "#555" }}>Applied 14:32 · 6 listings accounted for</span>
          <button
            type="button"
            className="wf-button"
            data-goto="batch-deploy-lofi-v1/review-loading"
            style={{ ...button, background: "#111", color: "#fff" }}
          >
            Re-plan remaining 1 →
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
            <p style={{ margin: 0, color: "#555" }}>{groups[row.group]}</p>
            <h2
              style={{
                margin: "4px 0 0",
                fontSize: 22,
                display: "flex",
                alignItems: "center",
                gap: 10,
              }}
            >
              <Marker done={row.done} />
              {row.title}
            </h2>
            <p style={{ margin: "4px 0 0", color: "#444" }}>
              {row.outcome} — {row.copy}
            </p>
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
          {row.note ? (
            <section style={{ ...pane, border: "1px solid #111" }}>
              <strong>Why it failed</strong>
              <p style={{ margin: "8px 0 0" }}>{row.note}</p>
              <button type="button" className="wf-button" style={{ ...button, marginTop: 12 }}>
                Retry removal →
              </button>
            </section>
          ) : (
            <p style={{ margin: 0, color: "#444" }}>
              The same evidence used in an individual deployment.
            </p>
          )}
          <div
            className="wf-diff"
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 16,
              alignItems: "start",
            }}
          >
            <Pane
              label="Before apply"
              lines={row.before}
              empty="Not on Etsy — this listing was created by this run."
            />
            <Pane
              label="On Etsy now"
              lines={row.done ? row.after : row.before}
              empty="Removed from Etsy."
              emphasis
            />
          </div>
        </div>
      </aside>
    </div>
  );
}
