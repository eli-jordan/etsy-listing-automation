import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { listListings } from "../api/listings";
import { cancelRun, getRun, markRunSeen } from "../api/runs";
import type { ListingSummary, RenderSnapshot, RunDetail } from "../types";
import { BatchAggregateStages } from "./batchDeploy/BatchAggregateStages";
import { BatchListingDrawer } from "./batchDeploy/BatchListingDrawer";
import { BatchListingGroups } from "./batchDeploy/BatchListingGroups";
import {
  batchDeployState,
  applyBatchRunEvent,
  initialBatchDeployState,
  type BatchDeployState,
  type BatchListingState,
} from "./batchDeploy/batchDeployState";
import { planGroup } from "./batchDeploy/batchDeployPresentation";
import { openRunStream, type RunStreamHandle } from "./deploy/runStream";
import { TERMINAL_PHASES } from "./deploy/runPhases";

function formatGeneratedAt(value: string | null): string {
  if (value === null) return "";
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? ""
    : `Generated ${new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date)}`;
}

function planFor(listing: BatchListingState) {
  return listing.plan ?? listing.reviewedPlan;
}

function reviewedListings(state: BatchDeployState): BatchListingState[] {
  return Object.values(state.listings).filter((listing) => listing.reviewedPlan !== null);
}

function requiredPreviewKeys(listings: readonly BatchListingState[]): string[] {
  const keys: string[] = [];
  for (const listing of listings) {
    const render = planFor(listing)?.stage_plans.find((stage) => stage.stage === "render");
    const snapshot = render?.snapshot as RenderSnapshot | null | undefined;
    for (const scene of snapshot?.scenes ?? []) {
      if (scene.state !== "cached" && !scene.preview) {
        keys.push(`${listing.listing}|${scene.template}|${scene.colour ?? ""}`);
      }
    }
  }
  return keys;
}

function planCounts(listings: readonly BatchListingState[]) {
  const counts = { add: 0, edit: 0, remove: 0 };
  for (const listing of listings) {
    const group = planGroup(planFor(listing), listing.planFailure);
    if (group === "add") counts.add += 1;
    if (group === "change") counts.edit += 1;
    if (group === "remove") counts.remove += 1;
  }
  return counts;
}

function isPlanning(phase: BatchDeployState["phase"]): boolean {
  return phase === "queued" || phase === "planning" || phase === "planned";
}

/** The stable workspace review route. It owns only run attachment and page
 * composition; event meaning remains in batchDeployState and all change
 * meaning remains in the engine-provided plans. PR5 will add the apply POST
 * and result overlay here, so this page deliberately keeps the authorization
 * control disabled for now. */
export function BatchDeployPage() {
  const { runId = "" } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [state, setState] = useState<BatchDeployState>(initialBatchDeployState);
  const [summaries, setSummaries] = useState<ListingSummary[]>([]);
  const [selectedListing, setSelectedListing] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const streamRef = useRef<RunStreamHandle | null>(null);
  const attachRef = useRef<(id: string) => void>(() => {});
  const activeRunRef = useRef<string | null>(null);
  const seenRef = useRef<string | null>(null);

  const openStream = useCallback((id: string, lastEventId: number) => {
    streamRef.current?.close();
    streamRef.current = openRunStream(id, {
      lastEventId,
      onEvent: (event) => {
        if (activeRunRef.current !== id) return;
        setState((current) => applyBatchRunEvent(current, event, "review"));
      },
      onError: () => {
        if (activeRunRef.current !== id) return;
        setStatus("Connection lost. Reconnecting…");
        void attachRef.current(id);
      },
    });
  }, []);

  const attach = useCallback(
    async (id: string) => {
      try {
        const loaded = await getRun(id);
        if (activeRunRef.current !== id) return;
        // PR4 is a workspace *plan* review. An apply run's event stream only
        // contains the listings it has reached so far; treating it as the
        // review source would turn partial replanning into seller-approved
        // truth. PR5 will add the linked review-run overlay explicitly.
        if (loaded.scope !== "workspace" || loaded.kind !== "plan") {
          streamRef.current?.close();
          setRun(null);
          setState(initialBatchDeployState);
          setSelectedListing(null);
          setStatus("This URL is not a workspace planning run. Return to Listings.");
          return;
        }
        setRun(loaded);
        setState(batchDeployState(loaded.events));
        const lastEventId = loaded.events.at(-1)?.id ?? 0;
        if (!TERMINAL_PHASES.has(loaded.phase)) openStream(id, lastEventId);
        else streamRef.current?.close();
        setStatus("");
      } catch {
        if (activeRunRef.current === id) {
          setStatus("Could not load this batch run. Return to Listings and try again.");
        }
      }
    },
    [openStream],
  );

  useEffect(() => {
    attachRef.current = (id) => void attach(id);
  }, [attach]);

  useEffect(() => {
    activeRunRef.current = runId;
    seenRef.current = null;
    let current = true;
    void listListings()
      .then((loaded) => {
        if (current) setSummaries(loaded);
      })
      .catch(() => {
        if (current) setStatus("Could not load listing details for this review.");
      });
    void Promise.resolve().then(() => attach(runId));
    return () => {
      current = false;
      if (activeRunRef.current === runId) activeRunRef.current = null;
      streamRef.current?.close();
    };
  }, [attach, runId]);

  useEffect(() => {
    if (
      run === null ||
      run.id !== runId ||
      run.seen ||
      seenRef.current === run.id ||
      !TERMINAL_PHASES.has(state.phase)
    ) {
      return;
    }
    seenRef.current = run.id;
    void markRunSeen(run.id);
  }, [run, runId, state.phase]);

  // Until this URL's detail has arrived, keep a previous route's plan out of
  // the approval surface. The state itself is reset by the detail replay, so
  // this also avoids synchronous setState calls in the route effect.
  const visibleState = run?.id === runId ? state : initialBatchDeployState;
  const listings = useMemo(() => reviewedListings(visibleState), [visibleState]);
  const plans = useMemo(
    () =>
      listings
        .map(planFor)
        .filter((plan): plan is NonNullable<ReturnType<typeof planFor>> => plan !== null),
    [listings],
  );
  const counts = useMemo(() => planCounts(listings), [listings]);
  const requiredPreviews = useMemo(() => requiredPreviewKeys(listings), [listings]);
  const previewsReady = requiredPreviews.every((key) => visibleState.previewsRendered.has(key));
  const runnableCount = plans.filter((plan) =>
    plan.stage_plans.some((stage) => stage.will_run),
  ).length;
  const nothingToDo =
    visibleState.phase === "ready" &&
    !Object.values(visibleState.listings).some(
      (listing) => listing.planFailure !== null || listing.failureMessage !== null,
    ) &&
    (plans.length === 0 ||
      plans.every((plan) => plan.stage_plans.every((stage) => !stage.will_run)));
  const showReview =
    visibleState.phase === "previewing" ||
    visibleState.phase === "ready" ||
    visibleState.phase === "failed";
  const summaryByName = useMemo(
    () => new Map(summaries.map((summary) => [summary.name, summary])),
    [summaries],
  );
  const selected =
    selectedListing === null ? null : (visibleState.listings[selectedListing] ?? null);
  const selectedSummary =
    selectedListing === null ? null : (summaryByName.get(selectedListing) ?? null);
  const selectedPlan = selected === null ? null : planFor(selected);

  async function handleBack() {
    if (run?.id === runId && run.kind === "plan" && isPlanning(visibleState.phase)) {
      await cancelRun(run.id).catch(() => false);
    }
    streamRef.current?.close();
    navigate("/listings");
  }

  const phase = visibleState.phase;
  const planning = isPlanning(phase);
  const headerTitle = planning ? "Planning all listings…" : "Review all changes";
  const planTimestamp = formatGeneratedAt(visibleState.generatedAt);

  return (
    <div className="editor batch-deploy-page">
      <div className="page-head">
        <button
          type="button"
          className="btn btn-secondary dv-back"
          onClick={() => void handleBack()}
        >
          ← Back to listings
        </button>
        <span className="page-head__sep">/</span>
        <h1 className="page-head__title">{headerTitle}</h1>
        <span className="page-head__meta">{planTimestamp}</span>
      </div>

      {status !== "" && (
        <p className="app__status" role="status">
          {status}
        </p>
      )}

      {planning && (
        <div className="dv-planning" role="status">
          <span className="dv-spinner" aria-hidden="true" />
          <div>
            <h2>Planning all listings…</h2>
            <p>
              Reading Printify and Etsy to work out what apply would change across this workspace.
              Nothing is written yet.
            </p>
          </div>
        </div>
      )}

      {phase === "previewing" && (
        <div className="dv-planning" role="status">
          <span className="dv-spinner" aria-hidden="true" />
          <div>
            <h2>Rendering previews…</h2>
            <p>
              Preview images are being prepared for review. Apply stays disabled until they are
              ready.
            </p>
          </div>
        </div>
      )}

      {phase === "failed" && (
        <div className="dv-callout dv-callout--blocked" role="alert">
          <strong>Planning could not finish.</strong>
          <p>Return to Listings and try a fresh workspace plan.</p>
        </div>
      )}

      {nothingToDo ? (
        <div className="dv-callout dv-callout--ok batch-deploy-empty" role="status">
          <div>
            <strong>Everything is up to date.</strong>
            <p>The all-listings plan found no changes to apply.</p>
          </div>
        </div>
      ) : (
        <>
          {visibleState.phase === "ready" && (
            <section className="batch-review-summary" aria-labelledby="batch-review-heading">
              <div>
                <span className="dv-eyebrow">Authoritative review</span>
                <h2 id="batch-review-heading">{listings.length} affected listings</h2>
                <p>
                  {counts.add} to add · {counts.edit} to edit · {counts.remove} to remove
                </p>
              </div>
              <span className="batch-review-summary__previews">
                {requiredPreviews.length === 0
                  ? "All required previews ready"
                  : `${requiredPreviews.filter((key) => visibleState.previewsRendered.has(key)).length} of ${requiredPreviews.length} previews ready`}
              </span>
            </section>
          )}

          {showReview && (
            <>
              <BatchAggregateStages
                plans={plans}
                listings={listings}
                onOpenListing={setSelectedListing}
              />
              <BatchListingGroups
                listings={Object.values(visibleState.listings)}
                onOpenListing={setSelectedListing}
              />
            </>
          )}
        </>
      )}

      <div className="dv-foot batch-deploy-footer">
        <p>
          {phase === "ready" && runnableCount > 0
            ? previewsReady
              ? "Apply runs exactly this plan, one listing at a time."
              : `Preview images before applying (${requiredPreviews.filter((key) => visibleState.previewsRendered.has(key)).length} of ${requiredPreviews.length})…`
            : nothingToDo
              ? "No remote changes were found."
              : "Apply unlocks once the reviewed previews are ready."}
        </p>
        <button
          type="button"
          className="btn btn-primary dv-big"
          disabled
          aria-label={`Apply ${runnableCount} listing${runnableCount === 1 ? "" : "s"}`}
          title={
            previewsReady
              ? "Applying reviewed plans is the next step"
              : "Preview images before applying"
          }
        >
          Apply {runnableCount} listing{runnableCount === 1 ? "" : "s"}
        </button>
      </div>

      <BatchListingDrawer
        open={selected !== null}
        listing={selected}
        summary={selectedSummary}
        previewsRendered={visibleState.previewsRendered}
        renderSnapshot={
          (selectedPlan?.stage_plans.find((stage) => stage.stage === "render")
            ?.snapshot as RenderSnapshot | null) ?? null
        }
        onClose={() => setSelectedListing(null)}
      />
    </div>
  );
}
