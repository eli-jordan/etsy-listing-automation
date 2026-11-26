import { useState } from "react";
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
const answersError = (field: string, changes: ShopChanges) => field in changes;

export function useShopSettings() {
  const [shop, setShop] = useState<ShopSettings | null>(null);
  const queue = useSaveQueue({
    send,
    answersError,
    fallbackMessage: "could not save shop.yaml",
    onSaved: (outcome) => setShop(outcome.shop),
  });
  const { loadedVersion, loadError, reload } = useQueuedFile({
    load: loadShop,
    queue,
    onLoaded: setShop,
    fallback: "could not read shop.yaml",
  });

  const { save } = queue;

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
    retry: queue.queueRetry,
    reload,
    locked: queue.locked,
  };
}
