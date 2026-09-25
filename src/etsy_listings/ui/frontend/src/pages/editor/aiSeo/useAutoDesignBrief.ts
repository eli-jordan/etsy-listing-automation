import { useCallback, useEffect, useRef, useState } from "react";
import { requestDesignBrief } from "../../../api/seo";
import type { AiSeoMode } from "./useAiSeoMode";

/**
 * The chain PRD 68 describes: attaching a design to a listing whose brief is
 * empty drafts one from the artwork, writes it through ordinary autosave, and
 * then starts the SEO request that filled brief unblocks.
 *
 * It lives in `ListingEditorPageContent`, beside `useAiSeoMode` and above the
 * tab strip, because both requests have to outlive the tab that is showing
 * when they start -- the design strip sits above the tabs, and a seller is
 * normally on **Variants** when they attach a design.
 *
 * ## Started by the pick, not inferred from the listing
 *
 * :func:`start` is called from the design strip's own `onPick`, so "a design
 * was attached" is an event this hook is told about rather than a difference
 * it works out by comparing renders. That is what lets the request go out
 * *immediately*, with no wait for a debounce, an autosave, or a name -- the
 * first version watched for the design to change and then waited for
 * `save.kind === "saved"`, which in the flow this feature exists for (create
 * a listing, attach a design, name it) meant waiting for something that had
 * not happened yet, and then losing the arming to the remount that naming
 * caused.
 *
 * Nothing about the request needs the listing to exist, or even to have a
 * garment chosen: `POST /api/ai/design-brief` takes the design alone, which
 * the pick has in hand.
 *
 * ## Once, and then never on its own
 *
 * `start` is only ever called from `onPick`, so there is no render path that
 * can fire a second request; a failure is reported and left alone. The seller
 * still has the AI Mode button and an empty Brief field they can type into.
 * An automatic retry loop against a metered CLI is the failure mode this rule
 * exists to make impossible (`docs/ui-listing-seo-interactions.md` section 1a).
 */

export type AutoBriefPhase = "idle" | "drafting" | "failed";

export interface AutoDesignBrief {
  /** `"drafting"` while the brief request is in flight; `"failed"` after one
   * that did not produce a usable brief, until the next pick. */
  phase: AutoBriefPhase;
  /** Draft a brief for a design just attached, unless the listing already
   * has one. Called from the design strip's `onPick`, with the ref exactly
   * as the listing stores it. */
  start: (ref: string) => void;
}

export function useAutoDesignBrief(
  brief: string,
  onUpdate: (patch: Record<string, unknown>) => void,
  onFlush: () => void,
  aiSeo: AiSeoMode,
): AutoDesignBrief {
  const [phase, setPhase] = useState<AutoBriefPhase>("idle");
  /** Set when a draft lands, cleared once generation has been asked for.
   * Generation cannot follow immediately: `aiSeo.available` stays false until
   * the brief has been saved and the readiness endpoint has seen the file. */
  const [drafted, setDrafted] = useState(0);
  const controllerRef = useRef<AbortController | null>(null);
  const generatedRef = useRef(0);

  // The editor's callbacks and current values as the pending request should
  // see them when it resolves, mirroring `useAiSeoMode`'s own `latest` refs: a
  // draft takes up to a minute, during which the seller keeps editing.
  const latest = useRef({ brief, onUpdate, onFlush });
  useEffect(() => {
    latest.current = { brief, onUpdate, onFlush };
  });

  const start = useCallback((ref: string) => {
    if (latest.current.brief.trim() !== "") return;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setPhase("drafting");
    requestDesignBrief(ref, controller.signal).then((outcome) => {
      if (controllerRef.current !== controller) return;
      controllerRef.current = null;
      if (outcome.kind !== "success") {
        setPhase(outcome.kind === "cancelled" ? "idle" : "failed");
        return;
      }
      setPhase("idle");
      // Still only into an empty field. The seller may have started typing
      // their own brief during the minute this took, and their text is the
      // authority on the design -- two authors of one field is the failure
      // to design out rather than detect afterwards.
      if (latest.current.brief.trim() !== "") return;
      latest.current.onUpdate({ brief: outcome.brief });
      latest.current.onFlush();
      setDrafted((token) => token + 1);
    });
  }, []);

  useEffect(() => () => controllerRef.current?.abort(), []);

  // The generation half. `aiSeo.available` is false until the readiness
  // endpoint has seen the written brief, so waiting on it is exactly what
  // makes this fire once, and only once it can succeed.
  useEffect(() => {
    if (drafted === 0 || generatedRef.current === drafted) return;
    if (!aiSeo.available || aiSeo.phase !== "idle") return;
    generatedRef.current = drafted;
    aiSeo.generate();
  }, [drafted, aiSeo]);

  return { phase, start };
}
