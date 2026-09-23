import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getWorkspace } from "../../../api/listings";
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
 * `getWorkspace()` is fetched fresh on every mount rather than threaded down
 * as a prop -- the same trade `AppShell` already makes for the sidebar's shop
 * name -- because the alternative (a workspace context reaching every editor
 * tab) is a bigger change than one cheap local `GET` justifies here. Its
 * `shop_name` is the only workspace-identifying fact the frontend has at all
 * (`WorkspaceSummary` carries nothing else); a `null` shop name -- a
 * workspace that hasn't configured one yet -- falls back to a fixed scope
 * string rather than leaving the proposal unscoped.
 */

const UNSCOPED_WORKSPACE = "workspace";

export type AiSeoPhase = "idle" | "loading" | "failed";

export interface AiSeoMode {
  /** Whether to render the AI Mode control at all -- the settled "Entry
   * point" decision is hidden, not disabled, so a caller renders nothing
   * rather than a disabled button when this is `false`. */
  available: boolean;
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
): AiSeoMode {
  const [shopName, setShopName] = useState<string | null>(null);
  // Only what the readiness *endpoint* answered -- whether the control is
  // actually shown also requires the client-observable prerequisites below,
  // computed straight from `detail` rather than mirrored into more state, so
  // clearing the brief hides the control immediately without waiting on
  // another round trip (or a synchronous `setState` inside the effect below,
  // which `react-hooks/set-state-in-effect` flags for good reason: nothing
  // here needs the extra render that resetting this to `false` would cost).
  const [remoteReady, setRemoteReady] = useState(false);
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

  useEffect(() => {
    if (!prerequisitesMet) return;
    let current = true;
    getWorkspace()
      .then((workspace) => {
        if (current) setShopName(workspace.shop_name);
      })
      .catch(() => {
        if (current) setShopName(null);
      });
    return () => {
      current = false;
    };
  }, [prerequisitesMet]);

  const workspaceScope = shopName ?? UNSCOPED_WORKSPACE;
  const listingScope = detail.name;
  const scope: AiSeoStorageScope = useMemo(
    () => ({ workspace: workspaceScope, listing: listingScope }),
    [workspaceScope, listingScope],
  );

  useEffect(() => {
    if (!prerequisitesMet) return;
    let current = true;
    getSeoReadiness(name)
      .then((response) => {
        if (current) setRemoteReady(response.ready);
      })
      .catch(() => {
        if (current) setRemoteReady(false);
      });
    return () => {
      current = false;
    };
  }, [prerequisitesMet, name]);

  const ready = prerequisitesMet && remoteReady;

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
    setStored(loadStoredProposal(scope));
  }

  const abortActive = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
  }, []);

  useEffect(() => abortActive, [abortActive]);

  const generate = useCallback(() => {
    abortActive();
    const controller = new AbortController();
    controllerRef.current = controller;
    setPhase("loading");
    const requestScope: AiSeoStorageScope = {
      workspace: shopName ?? UNSCOPED_WORKSPACE,
      listing: latestDetail.current.name,
    };
    requestSeoProposal(latestDetail.current.name, controller.signal).then((outcome) => {
      if (controllerRef.current !== controller) return;
      controllerRef.current = null;
      if (outcome.kind === "success") {
        const next = toStoredProposal(outcome.proposal, latestDetail.current);
        saveStoredProposal(requestScope, next);
        setStored(next);
        setPhase("idle");
      } else if (outcome.kind === "cancelled") {
        setPhase("idle");
      } else {
        setPhase("failed");
      }
    });
  }, [abortActive, shopName]);

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
