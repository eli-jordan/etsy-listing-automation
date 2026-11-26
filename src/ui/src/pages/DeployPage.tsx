import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  cancelRun,
  createRun,
  currentRun,
  getRun,
  isReviewedScope,
  markRunSeen,
} from "../api/runs";
import { getListing, tryGetListing } from "../api/listings";
import { sceneSource } from "../media";
import { stageWillRun, type ListingDetail } from "../types";
import { buildComparison, type DriftedField } from "./deploy/comparison";
import { ComparisonView } from "./deploy/ComparisonView";
import { scrollToDriftRow } from "./deploy/driftRowAnchor";
import { Callouts } from "./deploy/Callouts";
import { PriceTable } from "./deploy/PriceTable";
import { StepStrip } from "./deploy/StepStrip";
import { ApplyFooter } from "./deploy/ApplyFooter";
import { PublishDraftsToggle } from "./deploy/PublishDraftsToggle";
import { DeployHead } from "./deploy/DeployHead";
import {
  applyRunEvent,
  applyStarted,
  controlPhase,
  deployState,
  initialDeployState,
  type DeployState,
} from "./deploy/deployState";
import { openRunStream, type RunStreamHandle } from "./deploy/runStream";
import { isPlanInProgress, MARK_SEEN_GRACE_MS, TERMINAL_PHASES } from "./deploy/runPhases";

function stepStripHeading(phase: ReturnType<typeof controlPhase>): string {
  if (phase === "queued" || phase === "planning" || phase === "previewing")
    return "Checking each step";
  if (phase === "applied") return "What apply did";
  return "What apply will do";
}

function previewCounts(state: DeployState): { total: number; done: number } {
  const renderPlan = state.plan?.stage_plans.find((s) => s.stage === "render");
  const snapshot = renderPlan?.snapshot;
  const needed = (snapshot?.scenes ?? []).filter((s) => s.state !== "cached" && !s.preview);
  const done = needed.filter((s) =>
    state.previewsRendered.has(`${s.template}|${s.colour ?? ""}`),
  ).length;
  return { total: needed.length, done };
}

export function DeployPage() {
  const { name = "" } = useParams<{ name: string }>();
  const navigate = useNavigate();

  const [detail, setDetail] = useState<ListingDetail | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [waitingForBackup, setWaitingForBackup] = useState(false);
  const [state, setState] = useState<DeployState>(initialDeployState);
  const [applyRequested, setApplyRequested] = useState(false);
  const [publish, setPublish] = useState(false);
  const [deletedAfterApply, setDeletedAfterApply] = useState(false);
  const [openDrift, setOpenDrift] = useState<string | null>(null);
  const streamRef = useRef<RunStreamHandle | null>(null);
  const seenRef = useRef<string | null>(null);
  const leavingRef = useRef(false);
  const applyStartRef = useRef<Promise<void> | null>(null);
  const [status, setStatus] = useState("");
  const activeRunRef = useRef<string | null>(null);
  const reconnectRef = useRef<(id: string) => void>(() => {});

  const openStream = useCallback((id: string, lastEventId?: number) => {
    streamRef.current?.close();
    activeRunRef.current = id;
    streamRef.current = openRunStream(id, {
      ...(lastEventId === undefined ? {} : { lastEventId }),
      onEvent: (event) => setState((s) => applyRunEvent(s, event)),
      onError: () => {
        if (activeRunRef.current !== id) return;
        setStatus("Connection lost. Reconnecting…");
        reconnectRef.current(id);
      },
    });
  }, []);

  const reattachRun = useCallback(
    async (id: string) => {
      const detail = await getRun(id);
      setRunId(detail.id);
      setPublish(detail.publish);
      setWaitingForBackup(detail.waiting_for_backup);
      setState(deployState(detail.events));
      const last = detail.events.at(-1);
      if (TERMINAL_PHASES.has(detail.phase)) streamRef.current?.close();
      else openStream(detail.id, last?.id);
    },
    [openStream],
  );

  useEffect(() => {
    reconnectRef.current = (id) => {
      reattachRun(id)
        .then(() => setStatus(""))
        .catch(() => {
          if (activeRunRef.current === id) {
            setStatus("Could not reconnect to this run. Go back and try again.");
          }
        });
    };
  }, [reattachRun]);

  const startFreshPlan = useCallback(async () => {
    leavingRef.current = false;
    setApplyRequested(false);
    setStatus("");
    try {
      const result = await createRun({
        kind: "plan",
        scope: "listings",
        listings: [name],
        publish: false,
      });
      if (result.kind === "conflict") {
        const active = await getRun(result.activeRun);
        if (isReviewedScope(active)) {
          navigate(`/listings/deploy/${encodeURIComponent(active.id)}`, { replace: true });
          return;
        }
        await reattachRun(result.activeRun);
        return;
      }
      setState(initialDeployState);
      setRunId(result.run.id);
      setWaitingForBackup(result.run.waiting_for_backup);
      openStream(result.run.id);
    } catch {
      setStatus("Could not start a plan. Go back and try again.");
    }
  }, [name, navigate, openStream, reattachRun]);

  useEffect(() => {
    let current = true;
    getListing(name)
      .then((loaded) => {
        if (current) setDetail(loaded);
      })
      .catch(() => {});

    currentRun(name)
      .then(async (run) => {
        if (!current) return;
        if (run !== null && !TERMINAL_PHASES.has(run.phase)) {
          const detail = await getRun(run.id);
          if (!current) return;
          setRunId(detail.id);
          setPublish(detail.publish);
          setWaitingForBackup(detail.waiting_for_backup);
          setState(deployState(detail.events));
          const last = detail.events.at(-1);
          openStream(detail.id, last?.id);
          return;
        }
        if (run !== null && !run.seen) {
          const detail = await getRun(run.id);
          if (!current) return;
          setRunId(detail.id);
          setPublish(detail.publish);
          setState(deployState(detail.events));
          return;
        }
        await startFreshPlan();
      })
      .catch(() => {
        if (current) setStatus("Could not check this listing's runs. Go back and try again.");
      });

    return () => {
      current = false;
      activeRunRef.current = null;
      streamRef.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `startFreshPlan`/`openStream` are stable for a given `name`, and re-running this on their identity would refetch on every render.
  }, [name]);

  const phase = controlPhase(state, publish);
  const heldForBackup = phase === "queued" && waitingForBackup;

  useEffect(() => {
    if (runId === null || seenRef.current === runId) return;
    if (!TERMINAL_PHASES.has(state.phase)) return;

    const markSeen = () => {
      if (leavingRef.current) return;
      seenRef.current = runId;
      void markRunSeen(runId);
    };

    if (state.phase !== "applied") {
      markSeen();
      return;
    }
    const timer = window.setTimeout(markSeen, MARK_SEEN_GRACE_MS);
    return () => window.clearTimeout(timer);
  }, [runId, state.phase]);

  useEffect(() => {
    if (state.phase !== "applied") return;
    let current = true;
    tryGetListing(name).then((fresh) => {
      if (!current) return;
      if (fresh === null) setDeletedAfterApply(true);
      else setDetail(fresh);
    });
    return () => {
      current = false;
    };
  }, [state.phase, name]);

  async function handleBack() {
    leavingRef.current = true;
    // Applying begins with an async POST. A fast Back click can otherwise
    // navigate before that POST has registered the apply run, letting the
    // editor query the old (already-seen) plan and miss the new run forever.
    // Wait only for registration, not for the apply itself to finish.
    await applyStartRef.current;
    activeRunRef.current = null;
    streamRef.current?.close();
    if (runId !== null && isPlanInProgress(state.phase)) {
      await cancelRun(runId).catch(() => false);
    }
    navigate(deletedAfterApply ? "/listings" : `/listings/${encodeURIComponent(name)}`);
  }

  async function handleApply() {
    if (state.fingerprint === null) return;
    try {
      const result = await createRun({
        kind: "apply",
        scope: "listings",
        listings: [name],
        expect: { [name]: state.fingerprint },
        publish,
      });
      if (result.kind === "conflict") {
        await reattachRun(result.activeRun);
        return;
      }
      setState(applyStarted);
      setRunId(result.run.id);
      openStream(result.run.id);
    } catch {
      setApplyRequested(false);
      setStatus("Could not start the apply. Try again.");
    }
  }

  function beginApply() {
    setApplyRequested(true);
    const pending = handleApply();
    applyStartRef.current = pending;
    void pending.finally(() => {
      if (applyStartRef.current === pending) applyStartRef.current = null;
    });
  }

  const showPlanAgain = !["queued", "planning", "applying", "applied"].includes(phase);
  const showPublishToggle =
    state.plan?.publishable === true &&
    !applyRequested &&
    !["applying", "applied"].includes(phase) &&
    Object.keys(state.stageRuntime).length === 0;
  const comparison = state.plan ? buildComparison(state.plan) : null;
  const applyFocused =
    applyRequested ||
    phase === "applying" ||
    phase === "applied" ||
    Object.keys(state.stageRuntime).length > 0;
  const revealDrift = (field: DriftedField) => {
    if (field.expandable) setOpenDrift(field.key);
    scrollToDriftRow(field.key);
  };
  const { total: previewsTotal, done: previewsDone } = previewCounts(state);
  const appliedStepCount = state.plan?.stage_plans.filter(stageWillRun).length ?? 0;

  return (
    <div className="editor">
      <DeployHead
        name={name}
        status={detail?.status ?? null}
        phase={phase}
        waitingForBackup={heldForBackup}
        listingDeleted={deletedAfterApply}
        showPlanAgain={showPlanAgain}
        onBack={() => void handleBack()}
        onPlanAgain={() => void startFreshPlan()}
      />

      {status !== "" && (
        <p className="app__status" role="status">
          {status}
        </p>
      )}

      <div className="dv-stack">
        {(phase === "queued" || phase === "planning") && status === "" && (
          <div className="dv-planning">
            <span className="dv-spinner" aria-hidden="true" />
            {heldForBackup ? (
              <div>
                <h2>Waiting for backup</h2>
                <p>
                  A workspace backup is running. This plan starts as soon as it finishes. Nothing is
                  written yet.
                </p>
              </div>
            ) : (
              <div>
                <h2>Planning&hellip;</h2>
                <p>
                  Reading Printify and Etsy to work out what apply would change. Nothing is written
                  yet.
                </p>
              </div>
            )}
          </div>
        )}

        {state.failureMessage !== null && phase !== "stale" && (
          <div className="dv-callout dv-callout--blocked">
            <div>{state.failureMessage}</div>
          </div>
        )}

        {comparison && state.plan && detail && (
          <>
            {applyFocused && (
              <StepStrip
                plan={state.plan}
                stageRuntime={state.stageRuntime}
                heading={stepStripHeading(phase)}
              />
            )}
            <Callouts
              plan={state.plan}
              comparison={comparison}
              applied={phase === "applied"}
              {...(applyFocused ? {} : { onRevealDrift: revealDrift })}
            />
            {applyFocused ? (
              <details className="dv-approved-comparison">
                <summary>View approved before-and-after comparison</summary>
                <div className="dv-approved-comparison__body">
                  <ComparisonView
                    comparison={comparison}
                    listing={{
                      name: detail.name,
                      scene: sceneSource(detail.name, detail.design_content_hash),
                    }}
                    renderSnapshot={
                      state.plan.stage_plans.find((s) => s.stage === "render")?.snapshot ?? null
                    }
                    previewsRendered={state.previewsRendered}
                    collapsed={false}
                    etsyListingId={state.plan.etsy_listing_id}
                  />
                  {comparison.price?.changed && <PriceTable rows={comparison.priceRows} />}
                </div>
              </details>
            ) : (
              <>
                <ComparisonView
                  comparison={comparison}
                  listing={{
                    name: detail.name,
                    scene: sceneSource(detail.name, detail.design_content_hash),
                  }}
                  renderSnapshot={
                    state.plan.stage_plans.find((s) => s.stage === "render")?.snapshot ?? null
                  }
                  previewsRendered={state.previewsRendered}
                  collapsed={
                    !comparison.impacts.length &&
                    !comparison.drifted.length &&
                    comparison.hasEtsyListing
                  }
                  etsyListingId={state.plan.etsy_listing_id}
                  openDrift={openDrift}
                  onOpenDriftChange={setOpenDrift}
                />
                {comparison.price?.changed && <PriceTable rows={comparison.priceRows} />}
                <StepStrip
                  plan={state.plan}
                  stageRuntime={state.stageRuntime}
                  heading={stepStripHeading(phase)}
                />
              </>
            )}
          </>
        )}

        {showPublishToggle && (
          <PublishDraftsToggle
            checked={publish}
            disabled={phase === "queued" || phase === "planning" || phase === "previewing"}
            onChange={setPublish}
            goingLive={[name]}
            single
          />
        )}

        <ApplyFooter
          controlPhase={phase}
          waitingForBackup={heldForBackup}
          previewsTotal={previewsTotal}
          previewsDone={previewsDone}
          onApply={beginApply}
          appliedStepCount={appliedStepCount}
          backLabel={deletedAfterApply ? "← Back to listings" : "← Back to editor"}
          onBack={() => void handleBack()}
          etsyListingId={deletedAfterApply ? null : (detail?.etsy_listing_id ?? null)}
        />
      </div>
    </div>
  );
}
