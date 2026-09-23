import { useEffect, useRef, useState } from "react";
import { requestDesignBrief } from "../../../api/seo";
import type { SaveState } from "../../../hooks/useAutosave";
import type { ListingDetail } from "../../../types";
import type { AiSeoMode } from "./useAiSeoMode";

/**
 * The chain PRD 68 describes: attaching a design to a listing whose brief is
 * empty drafts one from the artwork, writes it through ordinary autosave, and
 * then starts the SEO request that filled brief unblocks.
 *
 * It lives in `ListingEditorShell`, not in `DetailsTab`, because the design
 * strip sits above the tabs and the seller is usually on **Variants** when
 * they attach one -- a hook mounted inside the Details tab would never see
 * the event that arms it, and would be torn down (aborting its own request)
 * the moment they switched tabs.
 *
 * ## One attach, one token
 *
 * `arming` is a counter, not a boolean, and every other piece of state here
 * is keyed to its current value. That is what makes "once per attach" a fact
 * about the data rather than a sequence of `setState` calls that have to
 * happen in the right order: the request effect fires only when its ref has
 * not yet seen this token, and the generation effect the same. Neither needs
 * to write state to stop itself running again, which is also how this hook
 * stays clear of `react-hooks/set-state-in-effect` -- a rule worth obeying
 * rather than silencing, since every cascading render it warns about here
 * would be one more chance to fire a second metered CLI request.
 *
 * ## What arms it
 *
 * The design *identity* changing, and nothing else. Not the editor mounting,
 * not typing, not another field. A listing that simply has a design and no
 * brief is an ordinary, common state -- opening one must not spend a
 * request. Only the transition does. `lastDesign` starts `null`, distinct
 * from `""` (no design), so the first render records what was already there
 * without treating it as an attach.
 *
 * ## Why firing is a separate step from arming
 *
 * At `/listings/new` the design is usually picked *before* the listing is
 * named, and every AI endpoint needs a saved listing. So the pick arms, and
 * the request goes out once the listing is saved and settled -- which in the
 * ordinary case is the very next render.
 *
 * ## Once, and then never on its own
 *
 * A failure settles the token and stops. There is no retry and no backoff:
 * the seller still has the AI Mode button and an empty Brief field they can
 * type into. An automatic retry loop against a metered CLI is the failure
 * mode this rule exists to make impossible
 * (`docs/ui-listing-seo-interactions.md` section 1a).
 */

export type AutoBriefPhase = "idle" | "drafting" | "failed";

export interface AutoDesignBrief {
  /** `"drafting"` while the brief request is in flight; `"failed"` after one
   * that did not produce a usable brief, until another attach re-arms the
   * chain. */
  phase: AutoBriefPhase;
  /** A design has been attached, but the listing is not saved yet, so
   * nothing has been asked for and nothing has been spent. */
  waiting: boolean;
}

type Outcome = "drafted" | "failed" | "cancelled";

/** A stable identity for `ListingDetail.design`, sorted so that a map which
 * arrived through a different key order is not mistaken for a new design.
 * `""` means no design at all. Mirrors `aiSeoStorage`'s own sort-before-
 * compare reasoning; kept separate because that one is about a *proposal's*
 * staleness and this one is about an attach, and sharing a function would
 * tie two unrelated rules together. */
function designIdentity(design: Record<string, string>): string {
  return Object.entries(design)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, value]) => `${key}=${value}`)
    .join("|");
}

export function useAutoDesignBrief(
  detail: ListingDetail,
  onUpdate: (patch: Record<string, unknown>) => void,
  onFlush: () => void,
  aiSeo: AiSeoMode,
  save?: SaveState,
): AutoDesignBrief {
  const [arming, setArming] = useState(0);
  const [settled, setSettled] = useState<{ token: number; outcome: Outcome } | null>(null);
  const [lastDesign, setLastDesign] = useState<string | null>(null);

  const controllerRef = useRef<AbortController | null>(null);
  /** The arming tokens each effect has already acted on. Refs rather than
   * state precisely because acting must not cause a render -- see the
   * "one attach, one token" note above. */
  const requestedRef = useRef(0);
  const generatedRef = useRef(0);
  // The editor's callbacks as the pending request should see them when it
  // resolves, mirroring `useAiSeoMode`'s own `latest` refs: a draft takes up
  // to a minute, during which the editor re-renders freely, and making these
  // effect dependencies would restart the request on an unrelated keystroke.
  const latestOnUpdate = useRef(onUpdate);
  const latestOnFlush = useRef(onFlush);
  useEffect(() => {
    latestOnUpdate.current = onUpdate;
    latestOnFlush.current = onFlush;
  });

  const identity = designIdentity(detail.design);
  const hasBrief = detail.brief.trim() !== "";

  // Adjusted during render rather than in an effect, the same way
  // `useAiSeoMode` restores its stored proposal: arming has to be visible in
  // the render that first shows the new design, so the effect below sees it
  // in that same commit.
  if (lastDesign !== identity) {
    const attached = lastDesign !== null && identity !== "";
    setLastDesign(identity);
    if (attached && !hasBrief) setArming((token) => token + 1);
  }

  const name = detail.name;
  const saved = save === undefined || save.kind === "saved";
  const canRequest = name !== "" && saved && !hasBrief;
  const open = arming > 0 && settled?.token !== arming;

  useEffect(() => {
    if (!open || !canRequest || requestedRef.current === arming) return;
    requestedRef.current = arming;
    const controller = new AbortController();
    controllerRef.current = controller;
    requestDesignBrief(name, controller.signal).then((outcome) => {
      if (controllerRef.current !== controller) return;
      controllerRef.current = null;
      if (outcome.kind === "success") {
        setSettled({ token: arming, outcome: "drafted" });
        latestOnUpdate.current({ brief: outcome.brief });
        latestOnFlush.current();
      } else {
        setSettled({
          token: arming,
          outcome: outcome.kind === "cancelled" ? "cancelled" : "failed",
        });
      }
    });
  }, [open, canRequest, arming, name]);

  // The seller typing their own brief while a draft is in flight ends the
  // chain: their text is the authority on the design, and two authors of one
  // field is the failure to design out rather than detect afterwards. The
  // abort resolves the request as `"cancelled"`, so the state change happens
  // in that callback rather than here.
  //
  // A *successful* draft also fills the brief, but clears `controllerRef`
  // before it does, so this cannot abort the request that just answered.
  useEffect(() => {
    if (hasBrief) controllerRef.current?.abort();
  }, [hasBrief]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  // The generation half. `aiSeo.available` is false until the readiness
  // endpoint has seen the written brief, so waiting on it is exactly what
  // makes this fire once, and only once it can succeed.
  useEffect(() => {
    if (settled?.outcome !== "drafted" || generatedRef.current === settled.token) return;
    if (!aiSeo.available || aiSeo.phase !== "idle") return;
    generatedRef.current = settled.token;
    aiSeo.generate();
  }, [settled, aiSeo]);

  const phase: AutoBriefPhase =
    open && canRequest ? "drafting" : settled?.outcome === "failed" ? "failed" : "idle";

  return { phase, waiting: open && !canRequest };
}
