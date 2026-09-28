import { useCallback, useEffect, useRef, useState } from "react";
import type { SaveState } from "../../../hooks/useAutosave";
import { getListingProposal, getSeoReadiness, resolveListingProposal } from "../../../api/seo";
import type { ListingDetail, ListingProposal, ProposalResolution } from "../../../types";
import { canToggleTag } from "./aiSeoTags";
import { type AiRun, useAiRun } from "./useAiRun";
import type { MarketPanelState } from "../market/MarketListingsPanel";
import { useMarketPanel } from "../market/useMarketPanel";

/**
 * Listing Details' **AI Mode** (AI SEO implementation plan, PR7): readiness,
 * the AI run behind the button (`useAiRun`; market-seo.md, *AI runs*), the
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
 * ## The proposal lives on the server (A41)
 *
 * The run caches its proposal before announcing it, so the editor reads it
 * with `GET …/proposal` on open and again after every save, and records a
 * choice or a dismissal with `PATCH …/resolution`. The server also decides
 * whether it is stale, against the *saved* listing, so the batch summary and
 * this editor agree; an edit shows up as stale once autosave lands it. A
 * stale proposal stays usable: the drawer heading names what changed
 * (PRD 74; UI doc §8).
 *
 * ## A batch's run (A40)
 *
 * While a batch row owns the listing, readiness says `batch_pending`: the
 * control stays disabled with the server's hint, and every
 * {@link BATCH_POLL_MS} this asks again and follows the listing's run once
 * the row's turn comes, so the editor shows the batch run live and opens
 * its drawers as a manual run's would.
 *
 * A resolution shows at once and is sent behind it. Every read and every
 * resolution takes a ticket, and only the latest one's answer is kept, so a
 * read that set off before a click cannot reopen the drawer it closed.
 */

export type AiSeoPhase = "idle" | "loading" | "failed";

type Section = keyof ProposalResolution;

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

const SECTIONS: Section[] = ["title", "tags", "lead"];

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
  /** Bumped by the batch poll, to ask readiness again. */
  const [poll, setPoll] = useState(0);
  const [record, setRecord] = useState<ListingProposal | null>(null);
  // `onUpdate`/`onFlush`/`detail` as a run's events should see them when they
  // arrive -- a run can take minutes, during which the seller may keep
  // editing, and the acceptance actions must always act on what is on screen
  // *now*, not what was on screen when `generate()` was called. Mirrors
  // `useAutosave`'s own `latest` ref for the same reason.
  const latestDetail = useRef(detail);
  const latestOnUpdate = useRef(onUpdate);
  const latestOnFlush = useRef(onFlush);
  const latestOnAdopt = useRef(onAdopt);
  const latestRecord = useRef(record);
  useEffect(() => {
    latestDetail.current = detail;
    latestOnUpdate.current = onUpdate;
    latestOnFlush.current = onFlush;
    latestOnAdopt.current = onAdopt;
    latestRecord.current = record;
  });
  /** The newest read or resolution; an answer to any older one is dropped. */
  const ticket = useRef(0);

  const read = useCallback((name: string) => {
    const mine = ++ticket.current;
    getListingProposal(name)
      .then((cached) => {
        if (mine === ticket.current) setRecord(cached);
      })
      .catch(() => {});
  }, []);

  // A live run's proposal is the record the server has just written, so it
  // opens the drawers without a second round trip.
  const onProposal = useCallback((proposal: ListingProposal) => {
    ++ticket.current;
    setRecord(proposal);
  }, []);

  // Only into an empty field: the seller may have started typing their own
  // brief while it was drafted, and their text wins. (The server made the
  // same check before it wrote, but the editor can be ahead of the disk.)
  const onBrief = useCallback((text: string) => {
    if (latestDetail.current.brief.trim() !== "") return;
    latestOnAdopt.current?.({ brief: text });
  }, []);

  const run = useAiRun(detail, save, { onBrief, onProposal });
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
  // succeeds, even if modified_at is unchanged -- and read the proposal
  // again with it, since staleness is judged against the saved listing.
  useEffect(() => {
    if (!canCheck) return;
    let current = true;
    getSeoReadiness(name)
      .then((response) => {
        if (current) {
          setRemoteReady(response.ready);
          setRemoteReason(response.reason ?? null);
          setBatchPending(response.batch_pending);
        }
      })
      .catch(() => {
        if (current) {
          setRemoteReady(false);
          setRemoteReason("Could not check AI setup.");
          setBatchPending(false);
        }
      });
    read(name);
    return () => {
      current = false;
    };
  }, [canCheck, name, detail.modified_at, save, read, poll]);

  const follow = run.follow;
  useEffect(() => {
    if (!batchPending) return;
    const timer = setInterval(() => {
      follow();
      setPoll((n) => n + 1);
    }, BATCH_POLL_MS);
    return () => clearInterval(timer);
  }, [batchPending, follow]);

  const ready = canCheck && remoteReady;
  const reason = canCheck && !ready ? (remoteReason ?? "Checking AI setup...") : null;
  const requirements = [
    { label: "Saved listing", ready: name !== "" && saved },
    { label: "Design selected", ready: hasDesign },
    { label: "SEO prompt and AI provider ready", ready },
  ];

  // Dropped during render, not from an effect, the same way `PreviewPanel`
  // adjusts state while rendering rather than paying for a second render:
  // a listing switch never briefly shows the previous listing's drawers
  // before the read for the new one comes back. A `useState` comparison, not
  // a ref, because refs may not be read during render (`react-hooks/refs`).
  const [loadedName, setLoadedName] = useState(name);
  if (loadedName !== name) {
    setLoadedName(name);
    setRecord(null);
  }

  const startRun = run.start;
  const generate = useCallback(
    () => startRun({ draftBrief: latestDetail.current.brief.trim() === "" }),
    [startRun],
  );
  const phase: AiSeoPhase = run.busy ? "loading" : run.phase === "failed" ? "failed" : "idle";

  const resolve = useCallback(
    (section: Section, state: "accepted" | "dismissed") => {
      const current = latestRecord.current;
      if (current === null) return;
      const listing = latestDetail.current.name;
      const mine = ++ticket.current;
      setRecord((shown) =>
        shown !== null && shown.generated_at === current.generated_at
          ? { ...shown, resolution: { ...shown.resolution, [section]: state } }
          : shown,
      );
      resolveListingProposal(listing, { generated_at: current.generated_at, [section]: state })
        .then((next) => {
          if (mine !== ticket.current) return;
          // Gone, or replaced by a newer proposal: show what is there now.
          if (next === null) read(listing);
          else setRecord(next);
        })
        .catch(() => {});
    },
    [read],
  );

  const chooseTitle = useCallback(
    (value: string) => {
      latestOnUpdate.current({ etsy: { title: value } });
      latestOnFlush.current();
      resolve("title", "accepted");
    },
    [resolve],
  );

  const rejectTitle = useCallback(() => resolve("title", "dismissed"), [resolve]);

  const chooseLead = useCallback(
    (value: string) => {
      latestOnUpdate.current({
        etsy: { description: { ...latestDetail.current.etsy.description, lead: value } },
      });
      latestOnFlush.current();
      resolve("lead", "accepted");
    },
    [resolve],
  );

  const rejectLead = useCallback(() => resolve("lead", "dismissed"), [resolve]);

  const toggleTag = useCallback((tag: string) => {
    const tags = latestDetail.current.etsy.tags;
    if (!canToggleTag(tags, tag)) return;
    const next = tags.includes(tag) ? tags.filter((t) => t !== tag) : [...tags, tag];
    latestOnUpdate.current({ etsy: { tags: next } });
    latestOnFlush.current();
  }, []);

  const acceptBestTags = useCallback(() => {
    const current = latestRecord.current;
    if (current === null) return;
    latestOnUpdate.current({ etsy: { tags: current.proposal.tags.slice(0, 13) } });
    latestOnFlush.current();
    resolve("tags", "accepted");
  }, [resolve]);

  const closeTags = useCallback(() => resolve("tags", "dismissed"), [resolve]);

  const pending = record !== null && SECTIONS.some((s) => record.resolution[s] === "pending");
  const proposal = pending ? record : null;

  return {
    available: ready,
    requirements,
    reason,
    phase,
    proposal,
    staleReason: proposal?.stale.is_stale ? proposal.stale.reasons.join(", ") : null,
    generate,
    draftsBrief: !hasBrief,
    cancel: run.cancel,
    failure: run.phase === "failed" ? run.message : null,
    startedAt: run.startedAt,
    run,
    market,
    chooseTitle,
    rejectTitle,
    chooseLead,
    rejectLead,
    toggleTag,
    acceptBestTags,
    closeTags,
  };
}
