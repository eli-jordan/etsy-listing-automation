import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getWorkspace } from "../../../api/listings";
import type { SaveState } from "../../../hooks/useAutosave";
import { getSeoReadiness, requestSeoProposal } from "../../../api/seo";
import type { ListingDetail } from "../../../types";
import {
  type AiSeoStorageScope,
  type StoredAiSeoProposal,
  isStale,
  loadStoredProposal,
  saveStoredProposal,
  toStoredProposal,
  updateUnresolved,
} from "./aiSeoStorage";
import { canToggleTag } from "./aiSeoTags";

/**
 * Listing Details' **AI Mode** (AI SEO implementation plan, PR7): readiness,
 * one request at a time with cancellation, the browser-local pending
 * proposal, staleness against the current editor state, and the three
 * independent per-field acceptance actions. `DetailsTab` is the one caller;
 * this hook exists separately so each of those concerns (readiness polling,
 * the abortable request, local-storage persistence) has one seam a test can
 * drive without rendering the whole tab.
 *
 * `getWorkspace()` supplies an opaque root identity for PRD 4's browser-only
 * proposal scope. Generation waits for it, so two roots with the same shop
 * name cannot restore each other's pending choices.
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
  /** Starts a request, or replaces the current proposal with a fresh one
   * (this is also what a seller's "Regenerate" click on a stale proposal
   * calls -- one control, since a request always produces one complete
   * proposal for all three fields). */
  generate: () => void;
  /** Aborts the in-flight request, if any, and returns to `"idle"` with no
   * proposal retained. */
  cancel: () => void;
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
  const [phase, setPhase] = useState<AiSeoPhase>("idle");
  const [stored, setStored] = useState<StoredAiSeoProposal | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  // `onUpdate`/`onFlush`/`detail` as the pending request should see them once
  // it resolves -- a request can take up to 60 seconds, during which the
  // seller may keep editing, and the acceptance actions must always act on
  // what is on screen *now*, not what was on screen when `generate()` was
  // called. Mirrors `useAutosave`'s own `latest` ref for the same reason.
  const latestDetail = useRef(detail);
  const latestOnUpdate = useRef(onUpdate);
  const latestOnFlush = useRef(onFlush);
  useEffect(() => {
    latestDetail.current = detail;
    latestOnUpdate.current = onUpdate;
    latestOnFlush.current = onFlush;
  });

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
        if (current) {
          setWorkspaceId(workspace.storage_id);
          setWorkspaceFailed(false);
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

  const abortActive = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
  }, []);

  useEffect(() => abortActive, [abortActive, scope]);

  const generate = useCallback(() => {
    if (workspaceId === null) return;
    abortActive();
    const controller = new AbortController();
    controllerRef.current = controller;
    setPhase("loading");
    const requestScope = scope;
    requestSeoProposal(latestDetail.current.name, controller.signal).then((outcome) => {
      if (controllerRef.current !== controller) return;
      controllerRef.current = null;
      if (outcome.kind === "success") {
        const next = toStoredProposal(outcome.proposal);
        saveStoredProposal(requestScope, next);
        setStored(next);
        setPhase("idle");
      } else if (outcome.kind === "cancelled") {
        setPhase("idle");
      } else {
        setPhase("failed");
      }
    });
  }, [abortActive, scope, workspaceId]);

  const cancel = useCallback(() => {
    abortActive();
    setPhase("idle");
  }, [abortActive]);

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
    cancel,
    chooseTitle,
    rejectTitle,
    chooseLead,
    rejectLead,
    toggleTag,
    acceptBestTags,
    closeTags,
  };
}
