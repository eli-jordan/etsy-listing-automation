import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { cancelRun, createRun, currentRun, getRun, markRunSeen } from "../api/runs";
import { getListing, tryGetListing } from "../api/listings";
import { StatusTag } from "../components/StatusTag";
import type { ListingDetail } from "../types";
import { buildComparison } from "./deploy/comparison";
import { ComparisonView } from "./deploy/ComparisonView";
import { Callouts } from "./deploy/Callouts";
import { PriceTable } from "./deploy/PriceTable";
import { StepStrip } from "./deploy/StepStrip";
import { ApplyFooter } from "./deploy/ApplyFooter";
import {
  applyRunEvent,
  controlPhase,
  deployState,
  initialDeployState,
  type DeployState,
} from "./deploy/deployState";
import { openRunStream, type RunStreamHandle } from "./deploy/runStream";
import { TERMINAL_PHASES } from "./deploy/runPhases";

/**
 * The deploy route: `/listings/:name/deploy` (docs/deploy-changes.md
 * decision 9). Reattaches to whatever run this listing already has, or
 * starts one -- the composing piece over the pure `deployState` reducer and
 * `comparison` builder, and the presentation modules that draw them.
 */

function metaText(phase: ReturnType<typeof controlPhase>): string {
  switch (phase) {
    case "queued":
      return "Waiting for another run…";
    case "planning":
      return "Planning…";
    case "previewing":
      return "Rendering previews…";
    case "ready-work":
    case "ready-blocked":
    case "ready-clean":
      return "Planned just now";
    case "applying":
      return "Applying…";
    case "applied":
      return "Applied just now";
    case "failed":
      return "The plan couldn’t be built. See the message above.";
    case "stale":
      return "This listing changed after it was planned.";
    case "cancelled":
      return "";
  }
}

function stepStripHeading(phase: ReturnType<typeof controlPhase>): string {
  if (phase === "queued" || phase === "planning" || phase === "previewing")
    return "Checking each step";
  if (phase === "applied") return "What apply did";
  return "What apply will do";
}

function previewCounts(state: DeployState): { total: number; done: number } {
  const renderPlan = state.plan?.stage_plans.find((s) => s.stage === "render");
  const snapshot = renderPlan?.snapshot as
    | { scenes?: { template: string; colour: string | null; state: string; preview: boolean }[] }
    | null
    | undefined;
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
  const [state, setState] = useState<DeployState>(initialDeployState);
  const [applyRequested, setApplyRequested] = useState(false);
  const [deletedAfterApply, setDeletedAfterApply] = useState(false);
  const streamRef = useRef<RunStreamHandle | null>(null);
  const seenRef = useRef<string | null>(null);
  const applyStartRef = useRef<Promise<void> | null>(null);

  const openStream = useCallback((id: string, lastEventId?: number) => {
    streamRef.current?.close();
    streamRef.current = openRunStream(id, {
      lastEventId,
      onEvent: (event) => setState((s) => applyRunEvent(s, event)),
    });
  }, []);

  const startFreshPlan = useCallback(async () => {
    setApplyRequested(false);
    const result = await createRun({ kind: "plan", listings: [name] });
    if (result.kind === "conflict") {
      const detail = await getRun(result.activeRun);
      setRunId(detail.id);
      setState(deployState(detail.events));
      const last = detail.events.at(-1);
      openStream(detail.id, last?.id);
      return;
    }
    setState(initialDeployState);
    setRunId(result.run.id);
    openStream(result.run.id);
  }, [name, openStream]);

  // Reattach or start (decision 9).
  useEffect(() => {
    let current = true;
    getListing(name)
      .then((loaded) => {
        if (current) setDetail(loaded);
      })
      .catch(() => {});

    currentRun(name).then(async (run) => {
      if (!current) return;
      if (run !== null && !TERMINAL_PHASES.has(run.phase)) {
        const detail = await getRun(run.id);
        if (!current) return;
        setRunId(detail.id);
        setState(deployState(detail.events));
        const last = detail.events.at(-1);
        openStream(detail.id, last?.id);
        return;
      }
      if (run !== null && !run.seen) {
        const detail = await getRun(run.id);
        if (!current) return;
        setRunId(detail.id);
        setState(deployState(detail.events));
        return;
      }
      await startFreshPlan();
    });

    return () => {
      current = false;
      streamRef.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `startFreshPlan`/`openStream` are stable for a given `name`, and re-running this on their identity would refetch on every render.
  }, [name]);

  const phase = controlPhase(state);

  // Mark a terminal run seen once it is showing -- "the deploy view marks a
  // finished run seen when it renders that run's result" (decision 9), true
  // whether it just finished while this page was watching or was already
  // finished on arrival.
  useEffect(() => {
    if (runId === null || seenRef.current === runId) return;
    if (!TERMINAL_PHASES.has(state.phase)) return;
    seenRef.current = runId;
    void markRunSeen(runId);
  }, [runId, state.phase]);

  // Status after apply is re-derived from the server, never assumed
  // (decision 10) -- a first deploy reads Deployed, not Live, and a partial
  // apply reads Dirty (A29).
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
    // Applying begins with an async POST. A fast Back click can otherwise
    // navigate before that POST has registered the apply run, letting the
    // editor query the old (already-seen) plan and miss the new run forever.
    // Wait only for registration, not for the apply itself to finish.
    await applyStartRef.current;
    streamRef.current?.close();
    // Only a plan run still under review (queued/planning/planned/previewing)
    // is worth asking the registry to cancel. An `apply` in progress is
    // never asked at all (decision 8: Back leaves, it never cancels one),
    // and a run already at a terminal phase -- "ready" included, a plan
    // run's own natural rest state, per `TERMINAL_PHASES` -- always answers
    // 409 from `registry.cancel`, since it refuses anything already
    // terminal. That case needs no cancel call at all: the "mark a terminal
    // run seen" effect above already marked it the moment its result
    // rendered, which is what keeps the editor's page head from dangling on
    // a stale *View progress* link.
    if (runId !== null && state.phase !== "applying" && !TERMINAL_PHASES.has(state.phase)) {
      await cancelRun(runId).catch(() => false);
    }
    navigate(deletedAfterApply ? "/listings" : `/listings/${encodeURIComponent(name)}`);
  }

  async function handleApply() {
    if (state.fingerprint === null) return;
    const result = await createRun({
      kind: "apply",
      listings: [name],
      expect: { [name]: state.fingerprint },
    });
    if (result.kind === "conflict") {
      const detail = await getRun(result.activeRun);
      setRunId(detail.id);
      setState(deployState(detail.events));
      const last = detail.events.at(-1);
      openStream(detail.id, last?.id);
      return;
    }
    // Keep the reviewed plan on screen while the apply run performs its
    // required re-plan. The fresh listing_planned event will replace it.
    setState((current) => ({
      ...initialDeployState,
      plan: current.plan,
      fingerprint: current.fingerprint,
    }));
    setRunId(result.run.id);
    openStream(result.run.id);
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
  const comparison = state.plan ? buildComparison(state.plan) : null;
  const applyFocused =
    applyRequested ||
    phase === "applying" ||
    phase === "applied" ||
    Object.keys(state.stageRuntime).length > 0;
  const { total: previewsTotal, done: previewsDone } = previewCounts(state);
  const appliedStepCount = state.plan?.stage_plans.filter((s) => s.will_run).length ?? 0;

  return (
    <div className="editor">
      <div className="page-head">
        <button
          type="button"
          className="btn btn-secondary dv-back"
          disabled={false}
          onClick={() => void handleBack()}
        >
          &larr; Back
        </button>
        <span className="page-head__crumb" onClick={() => void handleBack()}>
          Listings
        </span>
        <span className="page-head__sep">/</span>
        <span className="page-head__crumb" onClick={() => void handleBack()}>
          {name}
        </span>
        <span className="page-head__sep">/</span>
        <h1 className="page-head__title">Deploy</h1>
        {detail && <StatusTag status={detail.status} />}
        <span className="page-head__meta">{metaText(phase)}</span>
        {showPlanAgain && (
          <div className="page-head__actions dv-head-actions">
            <button
              type="button"
              className={phase === "stale" ? "btn btn-primary" : "btn btn-ghost"}
              onClick={() => void startFreshPlan()}
            >
              Plan again
            </button>
          </div>
        )}
      </div>

      <div className="dv-stack">
        {(phase === "queued" || phase === "planning") && (
          <div className="dv-planning">
            <span className="dv-spinner" aria-hidden="true" />
            <div>
              <h2>Planning&hellip;</h2>
              <p>
                Reading Printify and Etsy to work out what apply would change. Nothing is written
                yet.
              </p>
            </div>
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
            <Callouts plan={state.plan} comparison={comparison} applied={phase === "applied"} />
            {applyFocused ? (
              <details className="dv-approved-comparison">
                <summary>View approved before-and-after comparison</summary>
                <div className="dv-approved-comparison__body">
                  <ComparisonView
                    comparison={comparison}
                    detail={detail}
                    renderSnapshot={
                      (state.plan.stage_plans.find((s) => s.stage === "render")
                        ?.snapshot as never) ?? null
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
                  detail={detail}
                  renderSnapshot={
                    (state.plan.stage_plans.find((s) => s.stage === "render")?.snapshot as never) ??
                    null
                  }
                  previewsRendered={state.previewsRendered}
                  collapsed={!comparison.impacts.length && comparison.hasEtsyListing}
                  etsyListingId={state.plan.etsy_listing_id}
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

        <ApplyFooter
          controlPhase={phase}
          previewsTotal={previewsTotal}
          previewsDone={previewsDone}
          onApply={beginApply}
          appliedStepCount={appliedStepCount}
          backLabel={deletedAfterApply ? "← Back to listings" : "← Back to editor"}
          onBack={() => void handleBack()}
        />
      </div>
    </div>
  );
}
