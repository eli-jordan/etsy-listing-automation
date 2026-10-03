import { useEffect, useState } from "react";

export const meta = {
  title: "Batch deployment — review · v2",
  viewport: "laptop",
  description:
    "Two reads of the same stages: a run checklist at the top naming which listings each stage covers, and the individual page's step strip for one listing in the bottom sheet.",
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
// walks `RetractStage()` alone (`lifecycle.walk`), so it gets its own pipeline.
const pipeline = [
  { key: "render", label: "Render mockups" },
  { key: "printify_product", label: "Printify product" },
  { key: "publish", label: "Publish to Etsy" },
  { key: "etsy_listing", label: "Etsy listing" },
  { key: "etsy_media", label: "Etsy images" },
];
const retractPipeline = [{ key: "retract", label: "Remove from Etsy" }];

type StagePlan = { run: boolean; why: string; actions: string[] };
type Change = {
  id: string;
  title: string;
  copy: string;
  group: "add" | "change" | "remove";
  before: string[] | null;
  after: string[] | null;
  stages: Record<string, StagePlan>;
};

const changes: Change[] = [
  {
    id: "night-hike-club",
    title: "Night hike club · v2",
    copy: "new Printify product and Etsy draft",
    group: "add",
    before: null,
    after: ["Title: Night Hike Club Tee", "Price: 349 NOK", "Images: 4 · all new", "Tags: 13"],
    stages: {
      render: {
        run: true,
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
        why: "Not created yet",
        actions: ["Create product from Unisex Heavy Cotton Tee", "Attach 4 mockups"],
      },
      publish: {
        run: true,
        why: "Not on Etsy yet",
        actions: ["Publish as draft, mint listing id"],
      },
      etsy_listing: {
        run: true,
        why: "New listing fields",
        actions: ["Set title, description, price", "Set 13 tags"],
      },
      etsy_media: { run: true, why: "4 images to upload", actions: ["Upload 4 images in order"] },
    },
  },
  {
    id: "after-rain-trail",
    title: "After rain trail · v2",
    copy: "new Printify product and Etsy draft",
    group: "add",
    before: null,
    after: ["Title: After Rain Trail Tee", "Price: 349 NOK", "Images: 3 · all new", "Tags: 11"],
    stages: {
      render: {
        run: true,
        why: "3 scenes missing",
        actions: ["Render front · white", "Render front · moss", "Render folded · white"],
      },
      printify_product: {
        run: true,
        why: "Not created yet",
        actions: ["Create product from Unisex Heavy Cotton Tee", "Attach 3 mockups"],
      },
      publish: {
        run: true,
        why: "Not on Etsy yet",
        actions: ["Publish as draft, mint listing id"],
      },
      etsy_listing: {
        run: true,
        why: "New listing fields",
        actions: ["Set title, description, price", "Set 11 tags"],
      },
      etsy_media: { run: true, why: "3 images to upload", actions: ["Upload 3 images in order"] },
    },
  },
  {
    id: "mountain-sunrise-tee",
    title: "Mountain sunrise tee · v2",
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
      render: { run: true, why: "1 scene stale", actions: ["Re-render lifestyle · charcoal"] },
      printify_product: {
        run: true,
        why: "Price and title differ",
        actions: ["Update title to Mountain Sunrise Hiking Tee", "Set price 379 NOK"],
      },
      publish: { run: false, why: "Already published", actions: [] },
      etsy_listing: { run: true, why: "Title and price differ", actions: ["PATCH title, price"] },
      etsy_media: {
        run: true,
        why: "1 image to add",
        actions: ["Upload lifestyle · charcoal", "Reorder to 6 images"],
      },
    },
  },
  {
    id: "cedar-trail-shirt",
    title: "Cedar trail shirt · v2",
    copy: "colours and images",
    group: "change",
    before: ["Colours: 3", "Images: 4", "Price: 329 NOK"],
    after: ["Colours: 5 · 2 new", "Images: 6 · 2 new", "Price: 329 NOK · unchanged"],
    stages: {
      render: {
        run: true,
        why: "2 scenes missing",
        actions: ["Render front · forest", "Render front · clay"],
      },
      printify_product: {
        run: true,
        why: "2 colours to enable",
        actions: ["Enable forest, clay", "Attach 2 mockups"],
      },
      publish: { run: false, why: "Already published", actions: [] },
      etsy_listing: { run: false, why: "No changes", actions: [] },
      etsy_media: { run: true, why: "2 images to add", actions: ["Upload 2 images, keep order"] },
    },
  },
  {
    id: "fjord-mornings",
    title: "Fjord mornings · v2",
    copy: "description and tags",
    group: "change",
    before: ["Description: 240 characters", "Tags: 8"],
    after: ["Description: 610 characters", "Tags: 13 · 5 new"],
    stages: {
      render: { run: false, why: "No changes", actions: [] },
      printify_product: { run: true, why: "Description differs", actions: ["Update description"] },
      publish: { run: false, why: "Already published", actions: [] },
      etsy_listing: {
        run: true,
        why: "Description and tags differ",
        actions: ["PATCH description", "Set 13 tags · 5 new"],
      },
      etsy_media: { run: false, why: "No changes", actions: [] },
    },
  },
  {
    id: "old-logo-tee",
    title: "Old logo tee · v2",
    copy: "retract the remote listing, then remove its local files",
    group: "remove",
    before: ["Listing id: 1284660391", "Images: 5", "Price: 299 NOK"],
    after: null,
    stages: {
      retract: {
        run: true,
        why: "Marked for deletion",
        actions: ["Retract listing 1284660391", "Delete local files"],
      },
    },
  },
];

const groups = { add: "Add to Etsy", change: "Change on Etsy", remove: "Remove from Etsy" };
const stagesOf = (row: Change) => (row.group === "remove" ? retractPipeline : pipeline);
const runCount = (row: Change) => stagesOf(row).filter((s) => row.stages[s.key].run).length;

// The run's read of the same stages: which listings walk each one. `apply_listings`
// goes listing by listing, so a stage is checked off per listing, never run-wide.
const runStages = [...pipeline, ...retractPipeline].map((stage) => ({
  ...stage,
  items: changes
    .filter((c) => c.stages[stage.key]?.run)
    .map((c) => ({ id: c.id, title: c.title, why: c.stages[stage.key].why })),
}));

const work = changes.flatMap((change) =>
  stagesOf(change)
    .filter((stage) => change.stages[stage.key].run)
    .map((stage) => ({ listingId: change.id, stageKey: stage.key })),
);

type Phase = "review" | "applying" | "applied";
type StageState = "skip" | "queued" | "running" | "done";

function stateOf(row: Change, stageKey: string, phase: Phase, completed: number): StageState {
  if (!row.stages[stageKey].run) return "skip";
  if (phase === "review") return "queued";
  if (phase === "applied") return "done";
  const position = work.findIndex(
    (item) => item.listingId === row.id && item.stageKey === stageKey,
  );
  if (position < completed) return "done";
  if (position === completed) return "running";
  return "queued";
}

function Check({ state }: { state: StageState }) {
  const marks = { skip: "—", queued: "", running: "●", done: "✓" };
  return (
    <span
      aria-hidden="true"
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 15,
        height: 15,
        flex: "0 0 15px",
        border: "1px solid #111",
        background: state === "done" ? "#111" : "#fff",
        color: state === "done" ? "#fff" : "#111",
        fontSize: 10,
      }}
    >
      {marks[state]}
    </span>
  );
}

function RunChecklist({
  activeId,
  onOpen,
  phase,
  completed,
}: {
  activeId: string | null;
  onOpen: (id: string) => void;
  phase: Phase;
  completed: number;
}) {
  return (
    <section data-testid="run-stage-checklist" style={{ marginTop: 24 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: 16,
          marginBottom: 8,
        }}
      >
        <strong>Overall run stages</strong>
        <span style={{ color: "#555", fontSize: 13 }}>
          Counts advance as each listing finishes that stage
        </span>
      </div>
      <div style={{ border: "1px solid #999" }}>
        {runStages.map((stage, i) => {
          const states = stage.items.map((item) =>
            stateOf(
              changes.find((row) => row.id === item.id)!,
              stage.key,
              phase,
              completed,
            ),
          );
          const done = states.filter((state) => state === "done").length;
          const running = states.includes("running");
          return (
            <div
              key={stage.key}
              className="wf-stagerow"
              style={{
                display: "grid",
                gridTemplateColumns: "minmax(180px, 210px) 1fr",
                borderTop: i === 0 ? "none" : "1px solid #999",
              }}
            >
              <span
                style={{
                  padding: "12px 12px",
                  background: "#f6f6f6",
                  display: "flex",
                  flexDirection: "column" as const,
                  gap: 2,
                }}
              >
                <strong style={{ fontSize: 13 }}>{stage.label}</strong>
                <span
                  style={{
                    fontSize: 12,
                    color: running ? "#111" : "#555",
                    fontWeight: running ? 700 : 400,
                  }}
                >
                  {done}/{stage.items.length}
                  {running
                    ? " · running"
                    : done === stage.items.length && phase !== "review"
                      ? " · done"
                      : ""}
                </span>
              </span>
              <span
                style={{
                  padding: "10px 12px",
                  borderLeft: "1px solid #ccc",
                  display: "flex",
                  flexWrap: "wrap" as const,
                  gap: 8,
                }}
              >
                {stage.items.map((item, itemIndex) => (
                  <button
                    key={item.id}
                    type="button"
                    className="wf-row"
                    onClick={() => onOpen(item.id)}
                    style={{
                      ...button,
                      padding: "5px 9px",
                      fontSize: 12.5,
                      display: "flex",
                      alignItems: "center",
                      gap: 7,
                      border: item.id === activeId ? "1px solid #111" : "1px solid #ccc",
                    }}
                  >
                    <Check state={states[itemIndex]} />
                    {item.title}{" "}
                    <span style={{ color: "#555" }}>
                      · {states[itemIndex] === "running" ? "running now" : item.why}
                    </span>
                  </button>
                ))}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function ChangeRow({
  row,
  active,
  onOpen,
  phase,
  completed,
}: {
  row: Change;
  active: boolean;
  onOpen: () => void;
  phase: Phase;
  completed: number;
}) {
  const total = stagesOf(row).length;
  const states = stagesOf(row).map((stage) => stateOf(row, stage.key, phase, completed));
  const done = states.filter((state) => state === "done").length;
  const running = states.includes("running");
  const progress =
    phase === "review"
      ? `${runCount(row)} of ${total} stages`
      : running
        ? `${done}/${runCount(row)} · running`
        : done === runCount(row)
          ? "Done"
          : `${done}/${runCount(row)}`;
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
      <span
        style={{
          color: running ? "#111" : "#555",
          whiteSpace: "nowrap" as const,
          fontWeight: running ? 700 : 400,
        }}
      >
        {progress} →
      </span>
    </button>
  );
}

function StepStrip({ row, phase, completed }: { row: Change; phase: Phase; completed: number }) {
  const stages = stagesOf(row);
  return (
    <section>
      <p style={{ margin: "0 0 8px", color: "#555" }}>
        {phase === "review"
          ? "What apply will do"
          : phase === "applying"
            ? "Live progress for this listing"
            : "Stages completed for this listing"}{" "}
        · {runCount(row)} of {stages.length} stage{stages.length > 1 ? "s" : ""}
      </p>
      <div
        className="wf-steps"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
          border: "1px solid #999",
        }}
      >
        {stages.map((s, i) => {
          const plan = row.stages[s.key];
          const state = stateOf(row, s.key, phase, completed);
          return (
            <div
              key={s.key}
              style={{
                padding: 12,
                borderLeft: i === 0 ? "none" : "1px solid #999",
                background: state === "running" ? "#fff8d5" : plan.run ? "#fff" : "#f1f1f1",
              }}
            >
              <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Check state={state} />
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

function Diff({ row }: { row: Change }) {
  return (
    <div
      className="wf-diff"
      style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, alignItems: "start" }}
    >
      <Pane
        label="On Etsy now"
        lines={row.before}
        empty="Not on Etsy yet — this listing will be created."
      />
      <Pane
        label="After apply"
        lines={row.after}
        empty="Removed from Etsy, and its local files deleted."
        emphasis
      />
    </div>
  );
}

export default function BatchReviewBottomSheetWireframe() {
  const [index, setIndex] = useState(2);
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<Phase>("review");
  const [completed, setCompleted] = useState(0);
  const row = changes[index];
  const show = (id: string) => {
    setIndex(changes.findIndex((c) => c.id === id));
    setOpen(true);
  };

  useEffect(() => {
    if (phase !== "applying") return;
    if (completed >= work.length) {
      setPhase("applied");
      return;
    }
    const timer = window.setTimeout(() => setCompleted((count) => count + 1), 520);
    return () => window.clearTimeout(timer);
  }, [completed, phase]);

  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, []);

  const start = () => {
    setOpen(false);
    setCompleted(0);
    setPhase("applying");
  };
  const reset = () => {
    setOpen(false);
    setCompleted(0);
    setPhase("review");
  };
  const current = phase === "applying" ? work[completed] : undefined;
  const currentListing = current
    ? changes.find((change) => change.id === current.listingId)
    : undefined;

  return (
    <div style={page}>
      <style>{`.wf-button:hover,.wf-row:hover { background:#e5e5e5 !important; } @media(max-width:900px){.wf-sidebar{display:none!important}.wf-main{padding:24px!important}.wf-diff{grid-template-columns:1fr!important}.wf-stagerow{grid-template-columns:1fr!important}}`}</style>
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
          data-goto="batch-deploy-lofi-v2/listings"
          style={button}
        >
          ← Back to listings
        </button>
        <header style={{ marginTop: 22 }}>
          <p style={{ color: "#555", margin: 0 }}>Listings / Deploy changes</p>
          <h1 style={{ margin: "6px 0", fontSize: 30 }}>
            {phase === "review"
              ? "Review all changes"
              : phase === "applying"
                ? "Applying all changes"
                : "All changes applied"}
          </h1>
          <p style={{ margin: 0, color: "#444" }}>
            {phase === "review"
              ? "This plan covers every listing in your workspace. Nothing has been changed yet."
              : phase === "applying"
                ? `${currentListing?.title ?? "Finishing"} · ${completed}/${work.length} stage runs complete`
                : `6 listings finished · ${work.length} stage runs complete`}
          </p>
        </header>
        {phase === "applied" && (
          <section style={{ ...card, border: "1px solid #111", background: "#f3f8f2" }}>
            <strong>Deployment complete</strong>
            <p style={{ margin: "6px 0 0" }}>
              All 6 listings finished successfully. Open any listing to review its completed stages
              and final comparison.
            </p>
          </section>
        )}
        <section style={card}>
          <strong>6 listings affected</strong>
          <p style={{ margin: "6px 0 0" }}>2 to add · 3 to change · 1 marked for deletion</p>
          <p style={{ margin: "6px 0 0", color: "#555" }}>
            Apply takes one listing at a time, top to bottom. Open a listing to see the stages it
            will run and why.
          </p>
        </section>
        <RunChecklist
          activeId={open ? row.id : null}
          onOpen={show}
          phase={phase}
          completed={completed}
        />
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
                  active={open && row.id === c.id}
                  onOpen={() => show(c.id)}
                  phase={phase}
                  completed={completed}
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
            marginBottom: open ? 470 : 0,
          }}
        >
          <span>
            {phase === "review"
              ? "6 listings reviewed"
              : phase === "applying"
                ? `${completed}/${work.length} stage runs complete`
                : "6 listings applied"}
          </span>
          {phase === "review" ? (
            <button
              type="button"
              className="wf-button"
              onClick={start}
              style={{ ...button, background: "#111", color: "#fff" }}
            >
              Apply 6 changes →
            </button>
          ) : phase === "applying" ? (
            <button
              type="button"
              className="wf-button"
              disabled
              style={{ ...button, color: "#777" }}
            >
              Applying…
            </button>
          ) : (
            <button type="button" className="wf-button" onClick={reset} style={button}>
              Reset demo
            </button>
          )}
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
          <StepStrip row={row} phase={phase} completed={completed} />
          <Diff row={row} />
        </div>
      </aside>
    </div>
  );
}
