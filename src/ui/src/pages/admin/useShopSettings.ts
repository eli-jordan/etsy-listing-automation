import { useCallback, useEffect, useState } from "react";
import {
  getShop,
  saveShop,
  type SaveOutcome,
  type ShopChanges,
  type ShopField,
  type ShopSettings,
} from "../../api/shop";
import { useSaveQueue } from "./useSaveQueue";

export type { SaveStatus } from "./useSaveQueue";

export type FieldErrors = Partial<Record<ShopField, string>>;

const send = (revision: string, changes: ShopChanges) =>
  saveShop(revision, changes).then((outcome) =>
    outcome.kind === "saved" ? { ...outcome, revision: outcome.shop.revision } : outcome,
  );
const clears = (field: string, changes: ShopChanges) => field in changes;

/**
 * `shop.yaml` as the page sees it, over the file's save queue
 * (`useSaveQueue`): serialized revisioned saves, failures kept per field
 * until a save of that field succeeds, and a conflict that stops editing
 * until the seller reloads. Saved appears only after the server says so.
 *
 * `loadedVersion` changes only when a file is (re)loaded: the explicit
 * signal for controls to drop local drafts. A save's response updates
 * `shop` without it, so a newer local edit survives an older answer.
 */
export function useShopSettings() {
  const [shop, setShop] = useState<ShopSettings | null>(null);
  const [loadedVersion, setLoadedVersion] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const queue = useSaveQueue({ send, clears, fallback: "could not save shop.yaml" });
  const { reset, afterSaves } = queue;

  const adopt = useCallback(
    (loaded: ShopSettings) => {
      reset(loaded.revision);
      setShop(loaded);
      setLoadedVersion((version) => version + 1);
      setLoadError(null);
    },
    [reset],
  );
  const refuse = useCallback((error: unknown) => {
    setLoadError(error instanceof Error ? error.message : "could not read shop.yaml");
  }, []);
  const reload = useCallback(
    () => afterSaves(() => getShop()).then(adopt, refuse),
    [afterSaves, adopt, refuse],
  );

  useEffect(() => {
    getShop().then(adopt, refuse);
  }, [adopt, refuse]);

  const { save: enqueue, retry: resend } = queue;
  const save = useCallback(
    async (changes: ShopChanges): Promise<SaveOutcome | null> => {
      const outcome = await enqueue(changes);
      if (outcome?.kind === "saved") setShop(outcome.shop);
      return outcome;
    },
    [enqueue],
  );
  const retry = useCallback(() => {
    // Retry acknowledges saved values just like a field save. The queue
    // owns failure status, so an event handler need not catch its rejection.
    void resend()
      .then((outcome) => {
        if (outcome?.kind === "saved") setShop(outcome.shop);
      })
      .catch(() => undefined);
  }, [resend]);

  return {
    shop,
    loadedVersion,
    loadError,
    status: queue.status,
    fieldErrors: queue.fieldErrors as FieldErrors,
    save,
    retry,
    reload,
    locked: queue.locked,
  };
}
