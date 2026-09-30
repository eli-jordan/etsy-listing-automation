import { useCallback, useEffect, useRef, useState } from "react";
import { cancelAiRun, findAiRun, openAiRunStream, startAiRun } from "../../../api/aiRuns";
import type { EventStreamHandle } from "../../../api/sse";
import type { SaveState } from "../../../hooks/useAutosave";
import type {
  AiRunEvent,
  AiRunPhase,
  AiRunSummary,
  ListingDetail,
  MarketSnapshot,
  WorkflowStep,
} from "../../../types";

/**
 * The editor's side of an AI run (features/market-seo-20260924/spec.md, *AI runs*): the brief,
 * market research and the proposal as one server-side run per listing,
 * started here, followed through its event stream, and reattached to after a
 * reload or a return to the editor.
 *
 * Everything the UI shows about a run is a function of its events, so this
 * hook rebuilds its view from them and nothing else: `steps` is the latest
 * `step` event for each node, `queries` and `market` the latest of theirs.
 * That is what makes a reload show the same state again -- the stream
 * replays every event from the start (`openAiRunStream`), and the same
 * reduction lands in the same place.
 *
 * A written brief is handed over only for a live attachment: a finished
 * run's brief is already in the saved listing. Proposal events are forwarded
 * with attachment context; useProposalReview owns their identity and
 * precedence against durable cache reads and resolutions.
 *
 * ## The auto chain
 *
 * {@link AiRun.arm} is called from the design strip's pick while the brief is
 * empty. The chain then fires **once**, on the first successful save after
 * the pick that has a name, a design and a garment profile -- the first
 * moment the server can run it -- asking for a brief only if the field is
 * still empty then. That start raises {@link AiRun.autoNotice}; pressing
 * AI Mode does not. A new pick re-arms it; leaving the editor disarms it.
 * A run that fails is reported and left alone: an automatic retry against a
 * metered CLI is the failure mode "once" exists to rule out.
 */

export type AiRunViewPhase = "idle" | "starting" | AiRunPhase;

export interface AiRun {
  /** `"idle"` until this editor starts or finds a run; `"starting"` while
   * the `POST` is in flight; then the run's own phase. */
  phase: AiRunViewPhase;
  /** Starting or running: what disables the AI Mode button and shows
   * *Generating for…* and Cancel. */
  busy: boolean;
  /** The three nodes, brief → market → seo, each as its latest `step`
   * event left it. Empty until there is a run. */
  steps: WorkflowStep[];
  /** The three Etsy searches, once extraction has chosen them. */
  queries: string[] | null;
  /** The run's market snapshot, once research has finished. */
  market: MarketSnapshot | null;
  /** Why the run failed, or was refused. */
  message: string | null;
  /** When the run started (ms since the epoch), from the server. */
  startedAt: number | null;
  /** Who started the run: this editor, or the batch queue. `null`
   * until there is a run. */
  origin: AiRunSummary["origin"] | null;
  start: (options: { draftBrief: boolean; automatic?: boolean }) => void;
  cancel: () => void;
  /** Attaches to the listing's run if one is running that this editor is
   * not following yet -- a batch run whose turn came while the editor was
   * open. */
  follow: () => void;
  /** Arms the auto chain; see the module docstring. */
  arm: () => void;
  /** The auto chain started the run now on screen. A press of AI Mode does not set this. */
  autoNotice: boolean;
  dismissAutoNotice: () => void;
}

export interface AiRunHandlers {
  /** The server wrote a drafted brief into the listing. */
  onBrief?: (text: string) => void;
  /** Raw event and attachment context; proposal review owns replay precedence. */
  onProposal?: (event: Extract<AiRunEvent, { type: "proposal" }>, source: AiRunSummary) => void;
}

const LOST_STREAM = "Lost the connection to the AI run. Reload the page to see how it went.";
const START_FAILED = "Could not start AI Mode. Nothing changed.";

interface View {
  runId: string | null;
  phase: AiRunViewPhase;
  steps: WorkflowStep[];
  queries: string[] | null;
  market: MarketSnapshot | null;
  message: string | null;
  startedAt: number | null;
  origin: AiRunSummary["origin"] | null;
}

const IDLE: View = {
  runId: null,
  phase: "idle",
  steps: [],
  queries: null,
  market: null,
  message: null,
  startedAt: null,
  origin: null,
};

function viewOf(run: AiRunSummary): View {
  return {
    ...IDLE,
    runId: run.id,
    phase: run.phase,
    steps: run.steps,
    startedAt: Date.parse(run.created_at),
    origin: run.origin,
  };
}

function applyEvent(view: View, event: AiRunEvent): View {
  switch (event.type) {
    case "step": {
      const step: WorkflowStep = { id: event.id, state: event.state, detail: event.detail ?? null };
      const known = view.steps.some((s) => s.id === step.id);
      return {
        ...view,
        steps: known ? view.steps.map((s) => (s.id === step.id ? step : s)) : [...view.steps, step],
      };
    }
    case "queries":
      return { ...view, queries: event.queries };
    case "market":
      return { ...view, market: event.snapshot };
    case "phase":
      return { ...view, phase: event.phase, message: event.message ?? null };
    default:
      return view;
  }
}

export function useAiRun(
  detail: ListingDetail,
  save: SaveState | undefined,
  handlers: AiRunHandlers = {},
): AiRun {
  const [view, setView] = useState<View>(IDLE);
  const [autoNotice, setAutoNotice] = useState(false);
  const stream = useRef<EventStreamHandle | null>(null);
  /** Bumped by every start and attach: an answer or an event that arrives for
   * an older one is ignored. */
  const generation = useRef(0);
  /** While armed: the last save state the trigger judged (at first, the one
   * showing when the design was picked). */
  const armed = useRef<{ baseline: SaveState | undefined } | null>(null);
  const latest = useRef({ detail, save, handlers, runId: view.runId });
  useEffect(() => {
    latest.current = { detail, save, handlers, runId: view.runId };
  });

  const attach = useCallback((run: AiRunSummary) => {
    stream.current?.close();
    const mine = ++generation.current;
    // A finished run's brief is already in the file the editor loaded -- or
    // the seller has changed it since -- and its proposal is cached with the
    // seller's resolutions. Brief adoption is live-only; proposal review
    // receives the attachment context to decide which events remain current.
    const live = run.phase === "running";
    setView(viewOf(run));
    stream.current = openAiRunStream(run.id, {
      onEvent: (event) => {
        if (mine !== generation.current) return;
        setView((current) => applyEvent(current, event));
        if (event.type === "brief" && event.written && live) {
          latest.current.handlers.onBrief?.(event.text);
        }
        if (event.type === "proposal") {
          latest.current.handlers.onProposal?.(event, run);
        }
      },
      onError: () => {
        if (mine !== generation.current) return;
        setView((current) =>
          current.phase === "running"
            ? { ...current, phase: "failed", message: LOST_STREAM }
            : current,
        );
      },
    });
  }, []);

  const start = useCallback(
    ({ draftBrief, automatic = false }: { draftBrief: boolean; automatic?: boolean }) => {
      const listing = latest.current.detail.name;
      if (listing === "") return;
      setAutoNotice(automatic);
      stream.current?.close();
      stream.current = null;
      const mine = ++generation.current;
      setView({ ...IDLE, phase: "starting" });
      const failed = (message: string) => {
        if (mine === generation.current) setView({ ...IDLE, phase: "failed", message });
      };
      startAiRun(listing, { draftBrief })
        .then(async (result) => {
          if (mine !== generation.current) return;
          if (result.kind === "started") return attach(result.run);
          if (result.kind === "refused") return failed(result.reason);
          const active = await findAiRun(listing);
          if (mine !== generation.current) return;
          if (active === null) failed(START_FAILED);
          else attach(active);
        })
        .catch(() => failed(START_FAILED));
    },
    [attach],
  );

  const runId = view.runId;
  const running = view.phase === "running";
  const cancel = useCallback(() => {
    if (runId === null || !running) return;
    // The run stays busy until its own `cancelled` phase arrives, moments
    // later, once the provider's process tree is gone. Showing it idle
    // sooner would let a click on AI Mode land while the run still holds the
    // listing, and reattach to the run being cancelled.
    cancelAiRun(runId).catch(() => {});
  }, [runId, running]);

  const follow = useCallback(() => {
    const listing = latest.current.detail.name;
    if (listing === "") return;
    const mine = generation.current;
    findAiRun(listing)
      .then((run) => {
        if (run === null || run.phase !== "running" || mine !== generation.current) return;
        if (run.id !== latest.current.runId) attach(run);
      })
      .catch(() => {});
  }, [attach]);

  const arm = useCallback(() => {
    if (latest.current.detail.brief.trim() !== "") return;
    armed.current = { baseline: latest.current.save };
  }, []);

  // Reattach: the listing's current or latest run, replayed from its first
  // event. Only for a saved listing with a design -- nothing else can have
  // had a run -- and never over a run this editor has started since.
  const name = detail.name;
  const hasDesign = Object.keys(detail.design).length > 0;
  useEffect(() => {
    if (name === "" || !hasDesign) return;
    const mine = generation.current;
    let current = true;
    findAiRun(name)
      .then((run) => {
        if (current && run !== null && mine === generation.current) attach(run);
      })
      .catch(() => {});
    return () => {
      current = false;
    };
  }, [name, hasDesign, attach]);

  // The auto chain's trigger. Each save is judged once, in the render it
  // arrives in, where the editor still shows what that save wrote: an edit
  // made afterwards (choosing a garment profile) changes the editor at once
  // but not the file, and the chain must wait for the save that carries it.
  const brief = detail.brief;
  const garmentProfile = detail.garment_profile;
  useEffect(() => {
    const pick = armed.current;
    if (pick === null || save === undefined || save === pick.baseline) return;
    pick.baseline = save;
    if (save.kind !== "saved") return;
    if (name === "" || !hasDesign || garmentProfile.trim() === "") return;
    armed.current = null;
    start({ draftBrief: brief.trim() === "", automatic: true });
  }, [save, name, hasDesign, garmentProfile, brief, start]);

  useEffect(() => () => stream.current?.close(), []);

  return {
    phase: view.phase,
    busy: view.phase === "starting" || view.phase === "running",
    steps: view.steps,
    queries: view.queries,
    market: view.market,
    message: view.message,
    startedAt: view.startedAt,
    origin: view.origin,
    start,
    cancel,
    follow,
    arm,
    autoNotice,
    dismissAutoNotice: () => setAutoNotice(false),
  };
}
