import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { listListings } from "../api/listings";
import { cancelRun, createRun, getRun, markRunSeen } from "../api/runs";
import { stageWillRun, type ListingSummary, type PlanDTO, type RunDetail } from "../types";
import { BatchAggregateStages } from "./batchDeploy/BatchAggregateStages";
import { BatchListingDrawer } from "./batchDeploy/BatchListingDrawer";
import { BatchListingGroups } from "./batchDeploy/BatchListingGroups";
import {
  batchDeployState,
  applyBatchRunEvent,
  type BatchRunSource,
  initialBatchDeployState,
  type BatchDeployState,
  type BatchListingState,
} from "./batchDeploy/batchDeployState";
import { batchResult, planGroup } from "./batchDeploy/batchDeployPresentation";
import { BatchResultCallout, FooterAction, ReviewSummary } from "./batchDeploy/BatchDeployPanels";
import {
  BATCH_STAGE_TITLES,
  batchFooterMessage,
  batchStage,
  type BatchStage,
} from "./batchDeploy/batchDeployView";
import { openRunStream, type RunStreamHandle } from "./deploy/runStream";
import { MARK_SEEN_GRACE_MS, TERMINAL_PHASES } from "./deploy/runPhases";

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
  return state.reviewedListingOrder
    .map((listing) => state.listings[listing])
    .filter((listing): listing is BatchListingState => listing?.reviewedPlan !== null);
}

function requiredPreviewKeys(listings: readonly BatchListingState[]): string[] {
  const keys: string[] = [];
  for (const listing of listings) {
    const render = planFor(listing)?.stage_plans.find((stage) => stage.stage === "render");
    const snapshot = render?.snapshot;
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
  return (
    phase === "queued" || phase === "planning" || phase === "planned" || phase === "previewing"
  );
}

function isTerminalApply(state: BatchDeployState): boolean {
  return state.applyStarted && TERMINAL_PHASES.has(state.phase);
}

/** A plan with nothing left to do: ready, nothing failed, and no stage that
 * would run. */
function nothingToApply(state: BatchDeployState, plans: readonly PlanDTO[]): boolean {
  if (state.phase !== "ready") return false;
  const failed = Object.values(state.listings).some(
    (listing) => listing.planFailure !== null || listing.failureMessage !== null,
  );
  return !failed && plans.every((plan) => plan.stage_plans.every((stage) => !stageWillRun(stage)));
}

const DRAWER_MODES: Record<BatchStage, "applying" | "applied" | "review"> = {
  planning: "review",
  applying: "applying",
  applied: "applied",
  review: "review",
};

/** A workspace run and the review it applies (the run itself, for a plan),
 * or `null` when the run is not a workspace one. Throws when an apply has no
 * ready workspace review. */
async function loadWorkspaceRun(
  id: string,
): Promise<{ loaded: RunDetail; reviewed: RunDetail } | null> {
  const loaded = await getRun(id);
  if (loaded.scope !== "workspace") return null;
  if (loaded.kind !== "apply") return { loaded, reviewed: loaded };
  if (loaded.reviewed_run_id === null) throw new Error("apply run has no reviewed plan");
  const reviewed = await getRun(loaded.reviewed_run_id);
  if (reviewed.scope !== "workspace" || reviewed.kind !== "plan" || reviewed.phase !== "ready") {
    throw new Error("apply run has no ready workspace review");
  }
  return { loaded, reviewed };
}

/** The stable workspace route. It owns only run attachment and page composition;
 * event meaning remains in batchDeployState and all change meaning remains in
 * the engine-provided plans. A workspace apply keeps its linked review as the
 * approval surface and contributes only a live runtime overlay. */
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
  const applyStartRef = useRef<Promise<void> | null>(null);
  const leavingRef = useRef(false);
  const [applyPending, setApplyPending] = useState(false);

  const openStream = useCallback((id: string, lastEventId: number, source: BatchRunSource) => {
    streamRef.current?.close();
    streamRef.current = openRunStream(id, {
      lastEventId,
      onEvent: (event) => {
        if (activeRunRef.current !== id) return;
        setState((current) => applyBatchRunEvent(current, event, source));
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
        const runs = await loadWorkspaceRun(id);
        if (activeRunRef.current !== id) return;
        if (runs === null) {
          streamRef.current?.close();
          setRun(null);
          setState(initialBatchDeployState);
          setSelectedListing(null);
          setStatus("This URL is not a workspace planning run. Return to Listings.");
          return;
        }
        const { loaded, reviewed } = runs;
        setRun(loaded);
        setState(
          loaded.kind === "apply"
            ? batchDeployState(reviewed.events, loaded.events)
            : batchDeployState(loaded.events),
        );
        const lastEventId = loaded.events.at(-1)?.id ?? 0;
        if (!TERMINAL_PHASES.has(loaded.phase))
          openStream(id, lastEventId, loaded.kind === "apply" ? "apply" : "review");
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
    const id = run.id;
    const markSeen = () => {
      if (leavingRef.current) return;
      seenRef.current = id;
      void markRunSeen(id);
    };

    // A very small workspace apply can finish before the user's immediate
    // Back click is honoured -- Apply's own re-navigate to this apply run's
    // URL (handleApply) lands first and attaches here already terminal.
    // Give that exit intent a short window so Listings can still offer View
    // batch result; a result the user stays on is marked seen normally.
    if (!isTerminalApply(state)) {
      markSeen();
      return;
    }
    const timer = window.setTimeout(markSeen, MARK_SEEN_GRACE_MS);
    return () => window.clearTimeout(timer);
  }, [run, runId, state]);

  useEffect(() => {
    if (!isTerminalApply(state)) return;
    let current = true;
    void listListings()
      .then((loaded) => {
        if (current) setSummaries(loaded);
      })
      .catch(() => {
        if (current) setStatus("Could not refresh listing statuses after the batch result.");
      });
    return () => {
      current = false;
    };
  }, [state]);

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
  const readyPreviews = requiredPreviews.filter((key) =>
    visibleState.previewsRendered.has(key),
  ).length;
  const previewsReady = readyPreviews === requiredPreviews.length;
  const runnableCount = plans.filter((plan) => plan.stage_plans.some(stageWillRun)).length;
  const nothingToDo = nothingToApply(visibleState, plans);
  const summaryByName = useMemo(
    () => new Map(summaries.map((summary) => [summary.name, summary])),
    [summaries],
  );
  const selected =
    selectedListing === null ? null : (visibleState.listings[selectedListing] ?? null);
  const selectedSummary =
    selectedListing === null ? null : (summaryByName.get(selectedListing) ?? null);
  const selectedPlan = selected === null ? null : planFor(selected);

  const result = batchResult(visibleState);
  const terminalApply = isTerminalApply(visibleState);
  const applying = visibleState.applyStarted && !terminalApply;

  const followCreatedRun = useCallback(
    async (created: Awaited<ReturnType<typeof createRun>>) => {
      if (created.kind === "conflict") {
        const conflict = await getRun(created.activeRun);
        if (conflict.scope === "workspace") {
          navigate(`/listings/deploy/${encodeURIComponent(conflict.id)}`, { replace: true });
        } else {
          setStatus("A listing deploy is already running. Return to Listings to follow it.");
        }
      } else {
        navigate(`/listings/deploy/${encodeURIComponent(created.run.id)}`, { replace: true });
      }
    },
    [navigate],
  );

  const startWorkspacePlan = useCallback(async () => {
    try {
      const created = await createRun({ kind: "plan", scope: "workspace" });
      await followCreatedRun(created);
    } catch {
      setStatus("Could not start a fresh workspace plan.");
    }
  }, [followCreatedRun]);

  async function handleApply() {
    if (run?.kind !== "plan" || visibleState.phase !== "ready" || !previewsReady) return;
    const reviewed = reviewedListings(visibleState);
    const listingsToApply = reviewed.filter((listing) => listing.fingerprint !== null);
    if (listingsToApply.length !== reviewed.length) return;
    setSelectedListing(null);
    const pending = (async () => {
      try {
        const created = await createRun({
          kind: "apply",
          scope: "workspace",
          listings: listingsToApply.map((listing) => listing.listing),
          expect: Object.fromEntries(
            listingsToApply.map((listing) => [listing.listing, listing.fingerprint as string]),
          ),
          reviewed_run_id: run.id,
        });
        await followCreatedRun(created);
      } catch {
        setStatus("Could not start the reviewed workspace apply.");
      }
    })();
    applyStartRef.current = pending;
    setApplyPending(true);
    try {
      await pending;
    } finally {
      if (applyStartRef.current === pending) applyStartRef.current = null;
      setApplyPending(false);
    }
  }

  async function handleBack() {
    leavingRef.current = true;
    await applyStartRef.current;
    if (run?.id === runId && run.kind === "plan" && isPlanning(visibleState.phase)) {
      await cancelRun(run.id).catch(() => false);
    }
    streamRef.current?.close();
    navigate("/listings");
  }

  const phase = visibleState.phase;
  const planning = !visibleState.applyStarted && isPlanning(phase);
  const stage = batchStage({ planning, applying, terminalApply });
  const planTimestamp = formatGeneratedAt(visibleState.generatedAt);
  const showReview =
    planning ||
    visibleState.phase === "previewing" ||
    visibleState.phase === "ready" ||
    applying ||
    terminalApply;
  const showPlanningFailure = visibleState.phase === "failed" && !visibleState.applyStarted;

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
        <h1 className="page-head__title">{BATCH_STAGE_TITLES[stage]}</h1>
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

      {showPlanningFailure && (
        <div className="dv-callout dv-callout--blocked" role="alert">
          <strong>Planning could not finish.</strong>
          <p>Plan again to retry the workspace read, or return to Listings.</p>
        </div>
      )}

      {applying && (
        <div className="dv-callout dv-callout--drift" role="status">
          <strong>Applying reviewed changes.</strong>
          <p>Listings are updated one at a time and the run continues if one listing fails.</p>
        </div>
      )}

      {terminalApply && <BatchResultCallout result={result} />}

      {nothingToDo ? (
        <div className="dv-callout dv-callout--ok batch-deploy-empty" role="status">
          <div>
            <strong>Everything is up to date.</strong>
            <p>The all-listings plan found no changes to apply.</p>
          </div>
        </div>
      ) : (
        <>
          {visibleState.phase === "ready" && !visibleState.applyStarted && (
            <ReviewSummary
              affected={listings.length}
              counts={counts}
              readyPreviews={readyPreviews}
              requiredPreviews={requiredPreviews.length}
            />
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
          {batchFooterMessage({
            stage,
            result,
            canApply: phase === "ready" && runnableCount > 0,
            previewsReady,
            readyPreviews,
            requiredPreviews: requiredPreviews.length,
            nothingToDo,
          })}
        </p>
        <FooterAction
          stage={stage}
          planningFailed={showPlanningFailure}
          nothingToDo={nothingToDo}
          applyDisabled={
            applyPending ||
            phase !== "ready" ||
            runnableCount === 0 ||
            !previewsReady ||
            nothingToDo
          }
          runnableCount={runnableCount}
          previewsReady={previewsReady}
          onPlanAgain={() => void startWorkspacePlan()}
          onApply={() => void handleApply()}
        />
      </div>

      <BatchListingDrawer
        open={selected !== null}
        listing={selected}
        summary={selectedSummary}
        mode={DRAWER_MODES[stage]}
        previewsRendered={visibleState.previewsRendered}
        renderSnapshot={
          selectedPlan?.stage_plans.find((stage) => stage.stage === "render")?.snapshot ?? null
        }
        onClose={() => setSelectedListing(null)}
      />
    </div>
  );
}
