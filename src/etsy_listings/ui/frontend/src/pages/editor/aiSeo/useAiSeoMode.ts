import { useCallback, useEffect, useRef, useState } from "react";
import type { SaveState } from "../../../hooks/useAutosave";
import { getSeoReadiness } from "../../../api/seo";
import type { ListingDetail, ListingProposal } from "../../../types";
import { useProposalReview } from "./useProposalReview";
import { type AiRun, useAiRun } from "./useAiRun";
import type { MarketPanelState } from "../market/MarketListingsPanel";
import { useMarketPanel } from "../market/useMarketPanel";

/**
 * Listing Details' **AI Mode** (AI SEO implementation plan, PR7): readiness,
 * the AI run behind the button (`useAiRun`; features/market-seo-20260924/spec.md, *AI runs*), the
 * listing's cached proposal, and the three independent per-field acceptance
 * actions. `ListingEditorPageContent` owns it, above the tabs, because a run
 * outlives the tab it was started from; `DetailsTab` renders it.
 *
 * The run is exposed whole as `run`: its `steps` drive the page head's
 * indicator, and `market` is the top listings panel's state, built from the
 * run's market node and events and the listing's saved snapshot
 * (`useMarketPanel`). What this hook adds is what AI Mode does with a run's two actionable
 * events: a drafted brief goes into the field through `onAdopt` (the server
 * already wrote it, so it is not autosaved again), and a proposal opens the
 * drawers.
 *
 * ## The proposal lives on the server
 *
 * The run caches its proposal before announcing it, so the editor reads it
 * with `GET …/proposal` on open and again after every save, and records a
 * choice or a dismissal with `PATCH …/resolution`. The server also decides
 * whether it is stale, against the *saved* listing, so the batch summary and
 * this editor agree; an edit shows up as stale once autosave lands it. A
 * stale proposal stays usable: the drawer heading names what changed
 * (ADR-0047; UI doc §8).
 *
 * ## A batch's run
 *
 * While a batch row owns the listing, readiness says `batch_pending`: the
 * control stays disabled with the server's hint, and every
 * {@link BATCH_POLL_MS} this asks again and follows the listing's run once
 * the row's turn comes, so the editor shows the batch run live and opens
 * its drawers as a manual run's would.
 *
 * ## A deploy
 *
 * While a plan or apply holds the listing, readiness says `deploying`:
 * deploying takes precedence over AI (UI doc §8), so the control stays
 * disabled with the server's hint and asks again every {@link BATCH_POLL_MS}
 * until the deploy lets the listing go.
 *
 * useProposalReview owns cached/live proposal reconciliation and resolutions;
 * this module supplies readiness, run tracking and brief adoption.
 */

export type AiSeoPhase = "idle" | "loading" | "failed";

export interface AiSeoMode {
  /** Whether the AI Mode control can start a request. The button stays
   * visible and is disabled while this is false. */
  available: boolean;
  requirements: { label: string; ready: boolean }[];
  reason: string | null;
  phase: AiSeoPhase;
  /** The listing's cached proposal while any of its sections is still
   * pending, else `null` -- none was ever made, or every drawer has been
   * resolved (the server keeps the record either way). */
  proposal: ListingProposal | null;
  /** What changed since `proposal` was generated, from the server, or
   * `null` while it still describes the saved listing. Its choices stay
   * usable either way. */
  staleReason: string | null;
  /** Starts a run from the button, drafting the brief when the field is
   * empty, or replaces the current proposal with a fresh one (this is also
   * what a seller's "Regenerate" click on a stale proposal calls -- one
   * control, since a run always produces one complete proposal for all
   * three fields). */
  generate: () => void;
  /** The click will draft the brief, because the field is empty. A brief
   * the seller wrote is left alone. */
  draftsBrief: boolean;
  /** Cancels the run. A brief or snapshot it already wrote stays. */
  cancel: () => void;
  /** Why the last run failed or was refused, while `phase` is `"failed"`. */
  failure: string | null;
  /** When the current run started (ms since the epoch). *Generating for…*
   * counts from here, so a reload mid-run keeps counting. */
  startedAt: number | null;
  /** The run itself, for the page head's indicator. */
  run: AiRun;
  /** The top listings panel beside the fields, or `null` for none: what the
   * run is researching or found, else the listing's saved snapshot. */
  market: MarketPanelState | null;
  chooseTitle: (value: string) => void;
  rejectTitle: () => void;
  chooseLead: (value: string) => void;
  rejectLead: () => void;
  toggleTag: (tag: string) => void;
  acceptBestTags: () => void;
  closeTags: () => void;
}

/** How often the editor looks again while batch work owns the listing. */
export const BATCH_POLL_MS = 3000;

export function useAiSeoMode(
  detail: ListingDetail,
  onUpdate: (patch: Record<string, unknown>) => void,
  onFlush: () => void,
  save?: SaveState,
  /** Puts a value the server already wrote into the editor without saving
   * it again (`useAutosave`'s `adopt`). The drafted brief arrives this way. */
  onAdopt?: (patch: Record<string, unknown>) => void,
): AiSeoMode {
  // Only what the readiness *endpoint* answered -- whether the control is
  // enabled also requires the client-observable prerequisites below,
  // computed straight from `detail` rather than mirrored into more state, so
  // an edit the server has not seen yet disables the control immediately
  // without waiting on another round trip (or a synchronous `setState`
  // inside the effect below, which `react-hooks/set-state-in-effect` flags
  // for good reason: nothing here needs the extra render that resetting
  // this to `false` would cost).
  const [remoteReady, setRemoteReady] = useState(false);
  const [remoteReason, setRemoteReason] = useState<string | null>(null);
  const [batchPending, setBatchPending] = useState(false);
  const [deploying, setDeploying] = useState(false);
  /** Bumped by the batch poll, to ask readiness again. */
  const [poll, setPoll] = useState(0);
  const review = useProposalReview(detail, onUpdate, onFlush, save);
  // A run outlives edits; brief adoption must see the current field and callback.
  const latestDetail = useRef(detail);
  const latestOnAdopt = useRef(onAdopt);
  useEffect(() => {
    latestDetail.current = detail;
    latestOnAdopt.current = onAdopt;
  });
  // Only into an empty field: the seller may have started typing their own
  // brief while it was drafted, and their text wins. (The server made the
  // same check before it wrote, but the editor can be ahead of the disk.)
  const onBrief = useCallback((text: string) => {
    if (latestDetail.current.brief.trim() !== "") return;
    latestOnAdopt.current?.({ brief: text });
  }, []);

  const run = useAiRun(detail, save, { onBrief, onProposal: review.onProposal });
  const market = useMarketPanel(detail.name, run);

  const hasDesign = Object.keys(detail.design).length > 0;
  const hasBrief = detail.brief.trim() !== "";
  const name = detail.name;
  // The client-observable prerequisites, checked before any network call.
  // An empty brief is not one of them: the button drafts it. A listing with
  // no name or no design still never asks the network -- it cannot have had
  // a run, so it has no proposal either -- which is what keeps an ordinary
  // editor test whose fixture has neither from firing a `fetch` it never
  // mocked.
  const prerequisitesMet = name !== "" && hasDesign;
  const saved = save === undefined || save.kind === "saved";
  const canCheck = prerequisitesMet && saved;

  // A check after an edit can read the old file. Recheck when autosave
  // succeeds, even if modified_at is unchanged. Proposal review observes
  // the same saves to refresh server-computed staleness.
  useEffect(() => {
    if (!canCheck) return;
    let current = true;
    getSeoReadiness(name)
      .then((response) => {
        if (current) {
          setRemoteReady(response.ready);
          setRemoteReason(response.reason ?? null);
          setBatchPending(response.batch_pending);
          setDeploying(response.deploying);
        }
      })
      .catch(() => {
        if (current) {
          setRemoteReady(false);
          setRemoteReason("Could not check AI setup.");
          setBatchPending(false);
          setDeploying(false);
        }
      });
    return () => {
      current = false;
    };
  }, [canCheck, name, detail.modified_at, save, poll]);

  const follow = run.follow;
  const refreshProposal = review.refresh;
  useEffect(() => {
    if (!batchPending && !deploying) return;
    const timer = setInterval(() => {
      if (batchPending) follow();
      setPoll((n) => n + 1);
      refreshProposal();
    }, BATCH_POLL_MS);
    return () => clearInterval(timer);
  }, [batchPending, deploying, follow, refreshProposal]);

  const ready = canCheck && remoteReady;
  const reason = canCheck && !ready ? (remoteReason ?? "Checking AI setup...") : null;
  const requirements = [
    { label: "Saved listing", ready: name !== "" && saved },
    { label: "Design selected", ready: hasDesign },
    { label: "SEO prompt and AI provider ready", ready },
  ];

  const startRun = run.start;
  const generate = useCallback(
    () => startRun({ draftBrief: latestDetail.current.brief.trim() === "" }),
    [startRun],
  );
  const phase: AiSeoPhase = run.busy ? "loading" : run.phase === "failed" ? "failed" : "idle";

  return {
    available: ready,
    requirements,
    reason,
    phase,
    proposal: review.proposal,
    staleReason: review.staleReason,
    generate,
    draftsBrief: !hasBrief,
    cancel: run.cancel,
    failure: run.phase === "failed" ? run.message : null,
    startedAt: run.startedAt,
    run,
    market,
    ...review.actions,
  };
}
