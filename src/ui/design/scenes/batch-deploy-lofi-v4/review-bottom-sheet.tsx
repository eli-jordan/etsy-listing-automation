import { useEffect, useMemo, useState } from "react";
import { ComparisonView } from "./_snapshot/ComparisonView";
import { StepStrip } from "../../../src/pages/deploy/StepStrip";
import type { StageRuntimeStatus } from "../../../src/pages/deploy/deployState";
import {
  batchChanges,
  batchStageLabels,
  batchStageOrder,
  type BatchChangeFixture,
  type BatchGroup,
} from "./_fixtures";

export const meta = {
  title: "Batch deployment — review all changes · v4",
  viewport: "laptop",
  description:
    "Hi-fi clickable batch plan using the app's deploy step strip, comparison view, shell and design tokens with fake data.",
};

type Phase = "planning" | "review" | "applying" | "applied";
const groupLabels: Record<BatchGroup, string> = {
  add: "Add to Etsy",
  change: "Change on Etsy",
  remove: "Remove from Etsy",
};
const work = batchChanges.flatMap((listing) =>
  listing.plan.stage_plans
    .filter((stage) => stage.will_run)
    .map((stage) => ({ listingId: listing.id, stage: stage.stage })),
);

function stagePosition(listingId: string, stage: string): number {
  return work.findIndex((item) => item.listingId === listingId && item.stage === stage);
}

function listingRuntime(
  listing: BatchChangeFixture,
  phase: Phase,
  completed: number,
  startedAt: number,
): Record<string, StageRuntimeStatus> {
  if (phase === "review" || phase === "planning") return {};
  return Object.fromEntries(
    listing.plan.stage_plans.flatMap((stage) => {
      if (!stage.will_run) return [];
      const position = stagePosition(listing.id, stage.stage);
      if (phase === "applied" || position < completed)
        return [
          [stage.stage, { kind: "applied" as const, startedAt, finishedAt: startedAt + 700 }],
        ];
      if (position === completed)
        return [
          [
            stage.stage,
            { kind: "applying" as const, startedAt, log: `Working on ${listing.title}` },
          ],
        ];
      return [];
    }),
  );
}

function StageIcon({ state }: { state: "queued" | "running" | "done" }) {
  if (state === "running") return <span className="dv-spinner" aria-hidden="true" />;
  if (state === "done")
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="6.5" fill="var(--color-accent-2)" />
        <path
          d="m5 8.2 2 2 4-4.2"
          stroke="var(--color-bg)"
          strokeWidth="1.8"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8" r="6.5" fill="var(--color-accent)" />
      <path d="M6.5 5.2 10.5 8l-4 2.8Z" fill="var(--color-bg)" />
    </svg>
  );
}

function OverallStages({
  phase,
  completed,
  onOpen,
}: {
  phase: Phase;
  completed: number;
  onOpen: (id: string) => void;
}) {
  return (
    <div className="dv-stack" style={{ gap: 8 }}>
      <span className="dv-eyebrow">Overall run stages</span>
      <div className="dv-steps batch-stages">
        {batchStageOrder.map((stageName) => {
          const items = work.filter((item) => item.stage === stageName);
          const done = items.filter(
            (item) => phase === "applied" || stagePosition(item.listingId, item.stage) < completed,
          ).length;
          const running =
            phase === "applying"
              ? items.find((item) => stagePosition(item.listingId, item.stage) === completed)
              : undefined;
          const state = running
            ? "running"
            : phase !== "review" && done === items.length
              ? "done"
              : "queued";
          const runningListing = running
            ? batchChanges.find((listing) => listing.id === running.listingId)
            : undefined;
          return (
            <div
              key={stageName}
              className={`dv-step${state === "running" ? " dv-step--running" : state === "done" ? " dv-step--done" : ""}`}
            >
              <div className="dv-step__top">
                <StageIcon state={state} />
                <span className="dv-step__name">{batchStageLabels[stageName]}</span>
              </div>
              <div className="batch-stage__count">
                {done}/{items.length}
              </div>
              {runningListing ? (
                <button
                  type="button"
                  className="batch-stage__current"
                  onClick={() => onOpen(runningListing.id)}
                >
                  Running · {runningListing.title} →
                </button>
              ) : (
                <div className="dv-step__why">
                  {state === "done"
                    ? "All listings done"
                    : `${items.length} listing${items.length === 1 ? "" : "s"} will run`}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ListingRow({
  listing,
  phase,
  completed,
  onOpen,
}: {
  listing: BatchChangeFixture;
  phase: Phase;
  completed: number;
  onOpen: () => void;
}) {
  const positions = listing.plan.stage_plans
    .filter((stage) => stage.will_run)
    .map((stage) => stagePosition(listing.id, stage.stage));
  const done =
    phase === "applied"
      ? positions.length
      : positions.filter((position) => position < completed).length;
  const running = phase === "applying" && positions.includes(completed);
  return (
    <button
      type="button"
      className={`batch-listing${running ? " batch-listing--running" : ""}`}
      onClick={onOpen}
    >
      <span>
        <strong>{listing.title}</strong>
        <span className="batch-listing__summary">{listing.summary}</span>
      </span>
      <span className="batch-listing__progress">
        {phase === "review"
          ? `${positions.length} stages`
          : running
            ? `${done}/${positions.length} · running`
            : done === positions.length
              ? "Done"
              : `${done}/${positions.length}`}
        <span aria-hidden="true">→</span>
      </span>
    </button>
  );
}

export default function BatchReviewAppPrototype() {
  const [phase, setPhase] = useState<Phase>("planning");
  const [completed, setCompleted] = useState(0);
  const [selectedId, setSelectedId] = useState("mountain-sunrise-tee");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [startedAt, setStartedAt] = useState(0);
  const selected = batchChanges.find((listing) => listing.id === selectedId) ?? batchChanges[0]!;
  const selectedRuntime = useMemo(
    () => listingRuntime(selected, phase, completed, startedAt),
    [selected, phase, completed, startedAt],
  );

  useEffect(() => {
    if (phase !== "planning") return;
    const timer = window.setTimeout(() => setPhase("review"), 2200);
    return () => window.clearTimeout(timer);
  }, [phase]);

  useEffect(() => {
    if (phase !== "applying") return;
    if (completed >= work.length) {
      setPhase("applied");
      return;
    }
    const timer = window.setTimeout(() => setCompleted((value) => value + 1), 900);
    return () => window.clearTimeout(timer);
  }, [phase, completed]);

  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDrawerOpen(false);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, []);

  const open = (id: string) => {
    setSelectedId(id);
    setDrawerOpen(true);
  };
  const start = () => {
    setDrawerOpen(false);
    setCompleted(0);
    setStartedAt(Date.now());
    setPhase("applying");
  };
  const reset = () => {
    setDrawerOpen(false);
    setCompleted(0);
    setPhase("planning");
  };
  const current = phase === "applying" ? work[completed] : undefined;
  const currentListing = current
    ? batchChanges.find((listing) => listing.id === current.listingId)
    : undefined;

  return (
    <div className="batch-review">
      <style>{`
        .batch-review { padding-bottom:var(--space-8); }
        .batch-summary { display:flex; flex-wrap:wrap; align-items:center; gap:var(--space-2); }
        .batch-summary h2 { margin:0 var(--space-2) 0 0; font-size:21px; }
        .batch-stages { grid-template-columns:repeat(6,minmax(130px,1fr)); }
        .batch-stage__count { margin-top:4px; font-size:22px; line-height:1; font-weight:700; font-variant-numeric:tabular-nums; }
        .batch-stage__current { justify-content:flex-start; padding:0; border:0; background:transparent; font:700 11.5px/1.3 var(--font-body); text-align:left; color:var(--color-accent-800); }
        .batch-stage__current:hover { color:var(--color-accent-600); }
        .batch-group { display:grid; gap:var(--space-2); }
        .batch-group h2 { margin:0; font-size:19px; }
        .batch-listing { width:100%; display:flex; justify-content:space-between; gap:var(--space-3); padding:12px 14px; border:1px solid var(--color-divider); background:var(--color-neutral-100); font-family:var(--font-body); text-align:left; }
        .batch-listing:hover { border-color:var(--color-accent); background:color-mix(in srgb,var(--color-accent) 7%,var(--color-neutral-100)); }
        .batch-listing--running { border-color:var(--color-accent-400); background:var(--color-accent-100); }
        .batch-listing__summary { margin-left:var(--space-2); color:color-mix(in srgb,var(--color-text) 58%,transparent); font-weight:400; }
        .batch-listing__progress { display:flex; gap:var(--space-2); align-items:center; white-space:nowrap; color:color-mix(in srgb,var(--color-text) 62%,transparent); font-size:12.5px; font-variant-numeric:tabular-nums; }
        .batch-scrim { position:fixed; inset:0; z-index:40; background:color-mix(in srgb,var(--color-text) 28%,transparent); opacity:0; pointer-events:none; transition:opacity .18s ease; }
        .batch-scrim--open { opacity:1; pointer-events:auto; }
        .batch-drawer { position:fixed; z-index:41; left:240px; right:0; bottom:0; max-height:74vh; display:flex; flex-direction:column; background:var(--color-bg); border-top:1px solid var(--color-divider); box-shadow:var(--shadow-lg); transform:translateY(100%); transition:transform .22s ease-out; }
        .batch-drawer--open { transform:translateY(0); }
        .batch-drawer__handle { width:48px; height:4px; margin:var(--space-2) auto 0; border-radius:999px; background:var(--color-neutral-400); }
        .batch-drawer__head { display:flex; justify-content:space-between; gap:var(--space-3); align-items:flex-start; padding:var(--space-3) var(--space-6); border-bottom:1px solid var(--color-divider); }
        .batch-drawer__head h2 { margin:2px 0; font-size:22px; }
        .batch-drawer__head p { margin:0; color:color-mix(in srgb,var(--color-text) 58%,transparent); font-size:13px; }
        .batch-drawer__body { display:grid; gap:var(--space-4); padding:var(--space-4) var(--space-6) var(--space-6); overflow:auto; }
        @media(max-width:1000px){.batch-stages{grid-template-columns:repeat(3,minmax(140px,1fr))}.batch-stages .dv-step:nth-child(4){border-left:0}.batch-drawer{left:0}}
        @media(max-width:700px){.batch-stages{grid-template-columns:1fr 1fr}.batch-stages .dv-step:nth-child(odd){border-left:0}.batch-listing__summary{display:block;margin:2px 0 0}.batch-drawer__head,.batch-drawer__body{padding-left:var(--space-3);padding-right:var(--space-3)}}
        @media(prefers-reduced-motion:reduce){.batch-scrim,.batch-drawer{transition:none}}
      `}</style>

      <div className="page-head">
        <button
          type="button"
          className="btn btn-secondary dv-back"
          data-goto="batch-deploy-lofi-v4/listings"
        >
          ← Back
        </button>
        <span className="page-head__crumb">Listings</span>
        <span className="page-head__sep">/</span>
        <h1 className="page-head__title">Review all changes</h1>
        <span className="page-head__meta">
          {phase === "planning"
            ? "Planning…"
            : phase === "applying"
              ? `${completed}/${work.length} stage runs`
              : phase === "applied"
                ? "Applied just now"
                : "Planned just now"}
        </span>
      </div>

      <div className="dv-stack">
        {phase === "planning" ? (
          <div className="dv-planning">
            <span className="dv-spinner" aria-hidden="true" />
            <div>
              <h2>Planning all listings…</h2>
              <p>
                Reading Printify and Etsy to work out what apply would change across this workspace.
                Nothing is written yet.
              </p>
            </div>
          </div>
        ) : (
          <>
            {phase === "applied" && (
              <div className="dv-callout dv-callout--ok">
                <svg
                  className="dv-callout__icon"
                  viewBox="0 0 20 20"
                  fill="none"
                  stroke="var(--color-accent-2-700)"
                  strokeWidth="2"
                >
                  <path d="m5 10.5 3.2 3L15 6.5" />
                </svg>
                <div>
                  <strong>Deployed.</strong> All six listings finished and now match this plan.
                </div>
              </div>
            )}
            <div className="batch-summary">
              <h2>6 listings affected</h2>
              <span className="tag tag-accent-2">2 to add</span>
              <span className="tag tag-accent">3 to edit</span>
              <span className="tag tag-dirty">1 to remove</span>
              {currentListing && (
                <span className="page-head__meta">Now running · {currentListing.title}</span>
              )}
            </div>
            <OverallStages phase={phase} completed={completed} onOpen={open} />
            {(["add", "change", "remove"] as const).map((group) => (
              <section key={group} className="batch-group">
                <h2>
                  {groupLabels[group]}{" "}
                  <span className="page-head__meta">
                    · {batchChanges.filter((listing) => listing.group === group).length}
                  </span>
                </h2>
                {batchChanges
                  .filter((listing) => listing.group === group)
                  .map((listing) => (
                    <ListingRow
                      key={listing.id}
                      listing={listing}
                      phase={phase}
                      completed={completed}
                      onOpen={() => open(listing.id)}
                    />
                  ))}
              </section>
            ))}
            <div className="dv-foot">
              <p>
                {phase === "review"
                  ? "Apply runs exactly this plan, one listing at a time."
                  : phase === "applying"
                    ? "Running stages in order. You can leave; this keeps going."
                    : "All planned work finished."}
              </p>
              {phase === "review" ? (
                <button type="button" className="btn btn-primary dv-big" onClick={start}>
                  Apply 6 listings
                </button>
              ) : phase === "applying" ? (
                <button type="button" className="btn btn-primary dv-big" disabled>
                  <span className="dv-spinner" aria-hidden="true" />
                  Applying…
                </button>
              ) : (
                <button type="button" className="btn btn-secondary" onClick={reset}>
                  Replay prototype
                </button>
              )}
            </div>
          </>
        )}
      </div>

      <div
        className={`batch-scrim${drawerOpen ? " batch-scrim--open" : ""}`}
        onClick={() => setDrawerOpen(false)}
      />
      <aside
        className={`batch-drawer${drawerOpen ? " batch-drawer--open" : ""}`}
        aria-hidden={!drawerOpen}
      >
        <div className="batch-drawer__handle" />
        <header className="batch-drawer__head">
          <div>
            <span className="dv-eyebrow">{groupLabels[selected.group]}</span>
            <h2>{selected.title}</h2>
            <p>{selected.summary}</p>
          </div>
          <button
            type="button"
            className="btn btn-secondary"
            aria-label="Close"
            onClick={() => setDrawerOpen(false)}
          >
            Close
          </button>
        </header>
        <div className="batch-drawer__body">
          <StepStrip
            plan={selected.plan}
            stageRuntime={selectedRuntime}
            heading={
              phase === "applied"
                ? "What apply did"
                : phase === "applying"
                  ? "Live progress for this listing"
                  : "What apply will do"
            }
          />
          <ComparisonView
            comparison={selected.comparison}
            detail={selected.detail}
            renderSnapshot={null}
            previewsRendered={new Set()}
            collapsed={false}
            etsyListingId={selected.plan.etsy_listing_id}
          />
        </div>
      </aside>
    </div>
  );
}
