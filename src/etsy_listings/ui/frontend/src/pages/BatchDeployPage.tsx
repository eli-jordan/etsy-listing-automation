import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { listListings } from "../api/listings";
import { cancelRun, createRun, getRun, markRunSeen } from "../api/runs";
import { stageWillRun, type ListingSummary, type RunDetail } from "../types";
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

function countLabel(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
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
        const loaded = await getRun(id);
        if (activeRunRef.current !== id) return;
        if (loaded.scope !== "workspace") {
          streamRef.current?.close();
          setRun(null);
          setState(initialBatchDeployState);
          setSelectedListing(null);
          setStatus("This URL is not a workspace planning run. Return to Listings.");
          return;
        }
        let reviewed = loaded;
        if (loaded.kind === "apply") {
          if (loaded.reviewed_run_id === null) throw new Error("apply run has no reviewed plan");
          reviewed = await getRun(loaded.reviewed_run_id);
          if (
            reviewed.scope !== "workspace" ||
            reviewed.kind !== "plan" ||
            reviewed.phase !== "ready"
          ) {
            throw new Error("apply run has no ready workspace review");
          }
        }
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
    seenRef.current = run.id;
    void markRunSeen(run.id);
  }, [run, runId, state.phase]);

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
  const previewsReady = requiredPreviews.every((key) => visibleState.previewsRendered.has(key));
  const runnableCount = plans.filter((plan) => plan.stage_plans.some(stageWillRun)).length;
  const nothingToDo =
    visibleState.phase === "ready" &&
    !Object.values(visibleState.listings).some(
      (listing) => listing.planFailure !== null || listing.failureMessage !== null,
    ) &&
    (plans.length === 0 ||
      plans.every((plan) => plan.stage_plans.every((stage) => !stageWillRun(stage))));
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

  const startWorkspacePlan = useCallback(async () => {
    try {
      const created = await createRun({ kind: "plan", scope: "workspace" });
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
    } catch {
      setStatus("Could not start a fresh workspace plan.");
    }
  }, [navigate]);

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
    await applyStartRef.current;
    if (run?.id === runId && run.kind === "plan" && isPlanning(visibleState.phase)) {
      await cancelRun(run.id).catch(() => false);
    }
    streamRef.current?.close();
    navigate("/listings");
  }

  const phase = visibleState.phase;
  const planning = !visibleState.applyStarted && isPlanning(phase);
  const headerTitle = planning
    ? "Planning all listings…"
    : applying
      ? "Applying all changes…"
      : terminalApply
        ? "Batch result"
        : "Review all changes";
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

      {terminalApply && (
        <div
          className={`dv-callout ${result.partial ? "dv-callout--drift" : result.failed.length || result.stale.length ? "dv-callout--blocked" : "dv-callout--ok"}`}
          role={result.partial || result.failed.length || result.stale.length ? "alert" : "status"}
        >
          <strong>
            {result.partial
              ? "Batch partially applied."
              : result.stale.length > 0
                ? "Some listings became stale."
                : result.failed.length > 0
                  ? "Batch apply failed."
                  : "All planned work finished."}
          </strong>
          <p>
            {countLabel(result.succeeded.length, "listing")} succeeded
            {result.failed.length > 0 && ` · ${countLabel(result.failed.length, "listing")} failed`}
            {result.stale.length > 0 && ` · ${countLabel(result.stale.length, "listing")} stale`}
            {result.blocked.length > 0 &&
              ` · ${countLabel(result.blocked.length, "listing")} blocked`}
          </p>
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
          {visibleState.phase === "ready" && !visibleState.applyStarted && (
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
          {applying
            ? "Apply runs exactly this plan, one listing at a time."
            : terminalApply
              ? result.partial || result.failed.length > 0 || result.stale.length > 0
                ? "Review the affected listings, then plan again for the remaining work."
                : "All planned work finished."
              : phase === "ready" && runnableCount > 0
                ? previewsReady
                  ? "Apply runs exactly this plan, one listing at a time."
                  : `Preview images before applying (${requiredPreviews.filter((key) => visibleState.previewsRendered.has(key)).length} of ${requiredPreviews.length})…`
                : nothingToDo
                  ? "No remote changes were found."
                  : "Apply unlocks once the reviewed previews are ready."}
        </p>
        {applying ? (
          <button type="button" className="btn btn-primary dv-big" disabled>
            Applying…
          </button>
        ) : showPlanningFailure ? (
          <button
            type="button"
            className="btn btn-primary dv-big"
            onClick={() => void startWorkspacePlan()}
          >
            Try again
          </button>
        ) : nothingToDo ? (
          <button
            type="button"
            className="btn btn-primary dv-big"
            onClick={() => void startWorkspacePlan()}
          >
            Plan again
          </button>
        ) : terminalApply ? (
          <button
            type="button"
            className="btn btn-primary dv-big"
            onClick={() => void startWorkspacePlan()}
          >
            Plan again
          </button>
        ) : (
          <button
            type="button"
            className="btn btn-primary dv-big"
            disabled={
              applyPending ||
              phase !== "ready" ||
              runnableCount === 0 ||
              !previewsReady ||
              nothingToDo
            }
            onClick={() => void handleApply()}
            aria-label={`Apply ${runnableCount} listing${runnableCount === 1 ? "" : "s"}`}
            title={
              previewsReady
                ? "Applying reviewed plans is the next step"
                : "Preview images before applying"
            }
          >
            Apply {runnableCount} listing{runnableCount === 1 ? "" : "s"}
          </button>
        )}
      </div>

      <BatchListingDrawer
        open={selected !== null}
        listing={selected}
        summary={selectedSummary}
        mode={applying ? "applying" : terminalApply ? "applied" : "review"}
        previewsRendered={visibleState.previewsRendered}
        renderSnapshot={
          selectedPlan?.stage_plans.find((stage) => stage.stage === "render")?.snapshot ?? null
        }
        onClose={() => setSelectedListing(null)}
      />
    </div>
  );
}
