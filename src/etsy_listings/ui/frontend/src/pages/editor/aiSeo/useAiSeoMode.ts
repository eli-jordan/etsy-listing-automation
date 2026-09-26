import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getWorkspace } from "../../../api/listings";
import type { SaveState } from "../../../hooks/useAutosave";
import { getSeoReadiness } from "../../../api/seo";
import type { ListingDetail, SeoProposalResponse } from "../../../types";
import {
  type AiSeoStorageScope,
  type StoredAiSeoProposal,
  isStale,
  loadStoredProposal,
  receiveProposal,
  updateUnresolved,
} from "./aiSeoStorage";
import { canToggleTag } from "./aiSeoTags";
import { type AiRun, useAiRun } from "./useAiRun";

/**
 * Listing Details' **AI Mode** (AI SEO implementation plan, PR7): readiness,
 * the AI run behind the button (`useAiRun`; market-seo.md, *AI runs*), the
 * browser-local pending proposal, staleness against the current editor
 * state, and the three independent per-field acceptance actions.
 * `ListingEditorPageContent` owns it, above the tabs, because a run outlives
 * the tab it was started from; `DetailsTab` renders it.
 *
 * The run is exposed whole as `run`: its `steps` drive the page head's
 * indicator, and its `queries` and `market` are what the market panel will
 * read. What this hook adds is what AI Mode does with a run's two actionable
 * events: a drafted brief goes into the field through `onAdopt` (the server
 * already wrote it, so it is not autosaved again), and a proposal goes into
 * `aiSeoStorage`, which is what opens the drawers.
 *
 * `getWorkspace()` supplies an opaque root identity for PRD 4's browser-only
 * proposal scope, so two roots with the same shop name cannot restore each
 * other's pending choices. A proposal that arrives before it is kept until
 * it does.
 */

export type AiSeoPhase = "idle" | "loading" | "failed";

export interface AiSeoMode {
  /** Whether the AI Mode control can start a request. The button stays
   * visible and is disabled while this is false. */
  available: boolean;
  requirements: { label: string; ready: boolean }[];
  reason: string | null;
  phase: AiSeoPhase;
  /** The current pending proposal, or `null` once every drawer has resolved
   * (or none was ever requested). */
  proposal: StoredAiSeoProposal | null;
  /** Whether `proposal`'s choices are stale against the listing's current
   * values -- visible but not selectable until regenerated. Always `false`
   * when `proposal` is `null`. */
  stale: boolean;
  /** Starts a run from the button -- always without drafting, since the
   * button needs a brief -- or replaces the current proposal with a fresh
   * one (this is also what a seller's "Regenerate" click on a stale
   * proposal calls -- one control, since a run always produces one complete
   * proposal for all three fields). */
  generate: () => void;
  /** Cancels the run. A brief or snapshot it already wrote stays. */
  cancel: () => void;
  /** Why the last run failed or was refused, while `phase` is `"failed"`. */
  failure: string | null;
  /** When the current run started (ms since the epoch). *Generating for…*
   * counts from here, so a reload mid-run keeps counting. */
  startedAt: number | null;
  /** The run itself, for the page head's indicator and the market panel. */
  run: AiRun;
  chooseTitle: (value: string) => void;
  rejectTitle: () => void;
  chooseLead: (value: string) => void;
  rejectLead: () => void;
  toggleTag: (tag: string) => void;
  acceptBestTags: () => void;
  closeTags: () => void;
}

export function useAiSeoMode(
  detail: ListingDetail,
  onUpdate: (patch: Record<string, unknown>) => void,
  onFlush: () => void,
  save?: SaveState,
  /** Puts a value the server already wrote into the editor without saving
   * it again (`useAutosave`'s `adopt`). The drafted brief arrives this way. */
  onAdopt?: (patch: Record<string, unknown>) => void,
): AiSeoMode {
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [workspaceFailed, setWorkspaceFailed] = useState(false);
  // Only what the readiness *endpoint* answered -- whether the control is
  // enabled also requires the client-observable prerequisites below,
  // computed straight from `detail` rather than mirrored into more state, so
  // clearing the brief disables the control immediately without waiting on
  // another round trip (or a synchronous `setState` inside the effect below,
  // which `react-hooks/set-state-in-effect` flags for good reason: nothing
  // here needs the extra render that resetting this to `false` would cost).
  const [remoteReady, setRemoteReady] = useState(false);
  const [remoteReason, setRemoteReason] = useState<string | null>(null);
  const [stored, setStored] = useState<StoredAiSeoProposal | null>(null);
  // `onUpdate`/`onFlush`/`detail` as a run's events should see them when they
  // arrive -- a run can take minutes, during which the seller may keep
  // editing, and the acceptance actions must always act on what is on screen
  // *now*, not what was on screen when `generate()` was called. Mirrors
  // `useAutosave`'s own `latest` ref for the same reason.
  const latestDetail = useRef(detail);
  const latestOnUpdate = useRef(onUpdate);
  const latestOnFlush = useRef(onFlush);
  const latestOnAdopt = useRef(onAdopt);
  useEffect(() => {
    latestDetail.current = detail;
    latestOnUpdate.current = onUpdate;
    latestOnFlush.current = onFlush;
    latestOnAdopt.current = onAdopt;
  });
  /** The workspace's storage id once known, for the run's event handlers. */
  const workspaceRef = useRef<string | null>(null);
  /** A proposal that arrived before the workspace id did. The auto chain
   * starts with an empty brief, and the id is only asked for once there is
   * one, so the proposal waits here for it. */
  const awaiting = useRef<SeoProposalResponse | null>(null);

  const onProposal = useCallback((proposal: SeoProposalResponse) => {
    const workspace = workspaceRef.current;
    if (workspace === null) {
      awaiting.current = proposal;
      return;
    }
    setStored(receiveProposal({ workspace, listing: latestDetail.current.name }, proposal));
  }, []);

  // Only into an empty field: the seller may have started typing their own
  // brief while it was drafted, and their text wins. (The server made the
  // same check before it wrote, but the editor can be ahead of the disk.)
  const onBrief = useCallback((text: string) => {
    if (latestDetail.current.brief.trim() !== "") return;
    latestOnAdopt.current?.({ brief: text });
  }, []);

  const run = useAiRun(detail, save, { onBrief, onProposal });

  const hasDesign = Object.keys(detail.design).length > 0;
  const hasBrief = detail.brief.trim() !== "";
  const name = detail.name;
  // Every one of AI Mode's client-observable prerequisites, checked before
  // any network call at all -- not only the readiness endpoint, but also
  // `getWorkspace()` for local-storage scoping. A listing with no design or
  // brief yet (the common case: most listings, most of the time) never asks
  // the network anything, which matters beyond efficiency: an ordinary test
  // rendering an unrelated tab with a plain `ListingDetail` fixture should
  // never trigger a real `fetch()` it never mocked, and every fixture in
  // this codebase leaves `brief` empty except the ones this feature's own
  // tests write.
  const prerequisitesMet = name !== "" && hasDesign && hasBrief;
  const saved = save === undefined || save.kind === "saved";
  const canCheck = prerequisitesMet && saved;

  useEffect(() => {
    if (!prerequisitesMet) return;
    let current = true;
    getWorkspace()
      .then((workspace) => {
        if (!current) return;
        workspaceRef.current = workspace.storage_id;
        setWorkspaceId(workspace.storage_id);
        setWorkspaceFailed(false);
        const proposal = awaiting.current;
        awaiting.current = null;
        if (proposal !== null) {
          const scope = { workspace: workspace.storage_id, listing: latestDetail.current.name };
          setStored(receiveProposal(scope, proposal));
        }
      })
      .catch(() => {
        if (current) setWorkspaceFailed(true);
      });
    return () => {
      current = false;
    };
  }, [prerequisitesMet]);

  const listingScope = detail.name;
  const scope: AiSeoStorageScope = useMemo(
    () => ({ workspace: workspaceId ?? "", listing: listingScope }),
    [workspaceId, listingScope],
  );

  // A check after an edit can read the old file. Recheck when autosave
  // succeeds, even if modified_at is unchanged.
  useEffect(() => {
    if (!canCheck) return;
    let current = true;
    getSeoReadiness(name)
      .then((response) => {
        if (current) {
          setRemoteReady(response.ready);
          setRemoteReason(response.reason ?? null);
        }
      })
      .catch(() => {
        if (current) {
          setRemoteReady(false);
          setRemoteReason("Could not check AI setup.");
        }
      });
    return () => {
      current = false;
    };
  }, [canCheck, name, detail.modified_at, save]);

  const ready = canCheck && remoteReady && workspaceId !== null;
  const reason =
    canCheck && !ready
      ? workspaceFailed
        ? "Could not identify the workspace."
        : workspaceId === null
          ? "Checking workspace..."
          : (remoteReason ?? "Checking AI setup...")
      : null;
  const requirements = [
    { label: "Saved listing", ready: name !== "" && saved },
    { label: "Design selected", ready: hasDesign },
    { label: "Brief filled in", ready: hasBrief },
    { label: "SEO prompt and AI provider ready", ready },
  ];

  // Restored during render, not from an effect, the same way `PreviewPanel`
  // adjusts state while rendering rather than paying for a second render:
  // whenever the workspace/listing scope actually changes, re-read
  // `localStorage` for it immediately, so a listing switch never briefly
  // shows the previous listing's drawers before an effect gets to run. A
  // `useState` comparison, not a ref, because refs may not be read during
  // render (`react-hooks/refs`) -- this is exactly the "adjusting state when
  // a prop changes" case React's own docs use `useState` for.
  const [loadedScope, setLoadedScope] = useState(scope);
  if (loadedScope !== scope) {
    setLoadedScope(scope);
    setStored(workspaceId === null ? null : loadStoredProposal(scope));
  }

  const startRun = run.start;
  const generate = useCallback(() => startRun({ draftBrief: false }), [startRun]);
  const phase: AiSeoPhase = run.busy ? "loading" : run.phase === "failed" ? "failed" : "idle";

  const stale = stored !== null && isStale(stored, detail);

  const resolve = useCallback(
    (patch: Partial<StoredAiSeoProposal["unresolved"]>) => {
      setStored(updateUnresolved(scope, patch));
    },
    [scope],
  );

  const chooseTitle = useCallback(
    (value: string) => {
      if (stale) return;
      latestOnUpdate.current({ etsy: { title: value } });
      latestOnFlush.current();
      resolve({ title: false });
    },
    [resolve, stale],
  );

  const rejectTitle = useCallback(() => resolve({ title: false }), [resolve]);

  const chooseLead = useCallback(
    (value: string) => {
      if (stale) return;
      latestOnUpdate.current({
        etsy: { description: { ...latestDetail.current.etsy.description, lead: value } },
      });
      latestOnFlush.current();
      resolve({ lead: false });
    },
    [resolve, stale],
  );

  const rejectLead = useCallback(() => resolve({ lead: false }), [resolve]);

  const toggleTag = useCallback(
    (tag: string) => {
      if (stale) return;
      const tags = latestDetail.current.etsy.tags;
      if (!canToggleTag(tags, tag)) return;
      const next = tags.includes(tag) ? tags.filter((t) => t !== tag) : [...tags, tag];
      latestOnUpdate.current({ etsy: { tags: next } });
      latestOnFlush.current();
    },
    [stale],
  );

  const acceptBestTags = useCallback(() => {
    if (stale || stored === null) return;
    latestOnUpdate.current({ etsy: { tags: stored.proposal.tags.slice(0, 13) } });
    latestOnFlush.current();
    resolve({ tags: false });
  }, [resolve, stale, stored]);

  const closeTags = useCallback(() => resolve({ tags: false }), [resolve]);

  return {
    available: ready,
    requirements,
    reason,
    phase,
    proposal: stored,
    stale,
    generate,
    cancel: run.cancel,
    failure: run.phase === "failed" ? run.message : null,
    startedAt: run.startedAt,
    run,
    chooseTitle,
    rejectTitle,
    chooseLead,
    rejectLead,
    toggleTag,
    acceptBestTags,
    closeTags,
  };
}
