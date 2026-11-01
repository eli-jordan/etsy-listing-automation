import { useCallback, useState } from "react";
import {
  getShop,
  saveShop,
  type SaveOutcome,
  type ShopChanges,
  type ShopField,
  type ShopSettings,
} from "../../api/shop";
import { useQueuedFile } from "./useQueuedFile";
import { useSaveQueue } from "./useSaveQueue";

export type { SaveStatus } from "./useSaveQueue";

export type FieldErrors = Partial<Record<ShopField, string>>;

// Resolved at call time, so a reload reads whatever `getShop` is then.
const loadShop = () => getShop();
const send = (revision: string, changes: ShopChanges) =>
  saveShop(revision, changes).then((outcome) =>
    outcome.kind === "saved" ? { ...outcome, revision: outcome.shop.revision } : outcome,
  );
const clears = (field: string, changes: ShopChanges) => field in changes;

/**
 * `shop.yaml` as the page sees it, over the file's save queue
 * (`useSaveQueue`): serialized revisioned saves, failures kept per field
 * until that field succeeds or its failed choice is abandoned, and a conflict that stops editing
 * until the seller reloads. Saved appears only after the server says so.
 *
 * `loadedVersion` changes only when a file is (re)loaded: the explicit
 * signal for controls to drop local drafts. A save's response updates
 * `shop` without it, so a newer local edit survives an older answer.
 */
export function useShopSettings() {
  const [shop, setShop] = useState<ShopSettings | null>(null);
  const queue = useSaveQueue({
    send,
    clears,
    fallback: "could not save shop.yaml",
    // Every successful answer, a field save's or Retry's, is adopted here.
    onSaved: (outcome) => setShop(outcome.shop),
  });
  const { loadedVersion, loadError, reload } = useQueuedFile({
    load: loadShop,
    queue,
    onLoaded: setShop,
    fallback: "could not read shop.yaml",
  });

  const { save, retry: resend } = queue;
  // The queue owns failure status, so an event handler need not catch.
  const retry = useCallback(() => void resend().catch(() => undefined), [resend]);

  return {
    shop,
    loadedVersion,
    loadError,
    status: queue.status,
    fieldErrors: queue.fieldErrors as FieldErrors,
    pending: queue.pending,
    discard: queue.discard,
    refusal: queue.refusal,
    save: save as (
      changes: ShopChanges,
      options?: { retain?: boolean },
    ) => Promise<SaveOutcome | null>,
    retry,
    reload,
    locked: queue.locked,
  };
}
