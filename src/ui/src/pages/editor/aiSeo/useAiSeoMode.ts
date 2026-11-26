import { useCallback, useEffect, useRef, useState } from "react";
import type { SaveState } from "../../../hooks/listingAutosave";
import { getSeoReadiness } from "../../../api/seo";
import type { ListingDetail, ListingProposal } from "../../../types";
import { representative } from "../artwork";
import { useProposalReview } from "./useProposalReview";
import { type AiRun, useAiRun } from "./useAiRun";
import type { MarketPanelState } from "../market/MarketListingsPanel";
import { useMarketPanel } from "../market/useMarketPanel";

export type AiSeoPhase = "idle" | "loading" | "failed";

export interface AiSeoMode {
  available: boolean;
  requirements: { label: string; ready: boolean }[];
  reason: string | null;
  phase: AiSeoPhase;
  /** The listing's cached proposal while any of its sections is still
   * pending, else `null` -- none was ever made, or every drawer has been
   * resolved (the server keeps the record either way). */
  proposal: ListingProposal | null;
  staleReason: string | null;
  generate: () => void;
  draftsBrief: boolean;
  cancel: () => void;
  failure: string | null;
  startedAt: number | null;
  run: AiRun;
  market: MarketPanelState | null;
  chooseTitle: (value: string) => void;
  rejectTitle: () => void;
  chooseLead: (value: string) => void;
  rejectLead: () => void;
  toggleTag: (tag: string) => void;
  acceptBestTags: () => void;
  closeTags: () => void;
}

/** How often the editor looks again while batch work or a deploy owns the listing. */
export const READINESS_POLL_MS = 3000;

interface RemoteReadiness {
  ready: boolean;
  reason: string | null;
  batchPending: boolean;
  deploying: boolean;
}

const NOT_READY: RemoteReadiness = {
  ready: false,
  reason: null,
  batchPending: false,
  deploying: false,
};

export function useAiSeoMode(
  detail: ListingDetail,
  onUpdate: (patch: Record<string, unknown>) => void,
  onFlush: () => void,
  save?: SaveState,
  /** Puts a value the server already wrote into the editor without saving
   * it again (`useAutosave`'s `adopt`). The drafted brief arrives this way. */
  onAdopt?: (patch: Record<string, unknown>) => void,
): AiSeoMode {
  // Only what the endpoint answered. The prerequisites below come straight
  // from `detail`, so an edit the server has not seen yet disables the
  // control at once.
  const [remote, setRemote] = useState<RemoteReadiness>(NOT_READY);
  const { batchPending, deploying } = remote;
  const [poll, setPoll] = useState(0);
  const review = useProposalReview(detail, onUpdate, onFlush, save);
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

  const hasDesign = representative(detail.design) !== null;
  const hasBrief = detail.brief.trim() !== "";
  const name = detail.name;
  // Checked before any network call. An empty brief is not one: the button
  // drafts it. A listing with no name or no design cannot have had a run.
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
          setRemote({
            ready: response.ready,
            reason: response.reason ?? null,
            batchPending: response.batch_pending,
            deploying: response.deploying,
          });
        }
      })
      .catch(() => {
        if (current) setRemote({ ...NOT_READY, reason: "Could not check AI setup." });
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
    }, READINESS_POLL_MS);
    return () => clearInterval(timer);
  }, [batchPending, deploying, follow, refreshProposal]);

  const ready = canCheck && remote.ready;
  const reason = canCheck && !ready ? (remote.reason ?? "Checking AI setup...") : null;
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
  const settledPhase = run.phase === "failed" ? "failed" : "idle";
  const phase: AiSeoPhase = run.busy ? "loading" : settledPhase;

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
