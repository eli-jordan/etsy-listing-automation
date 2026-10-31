import { useCallback, useEffect, useRef, useState } from "react";
import {
  getShop,
  saveShop,
  type SaveOutcome,
  type ShopChanges,
  type ShopField,
  type ShopSettings,
} from "../../api/shop";

export type SaveStatus =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved" }
  | { kind: "error"; message: string }
  | { kind: "conflict"; message: string };

export type FieldErrors = Partial<Record<ShopField, string>>;

/**
 * `shop.yaml` as the page sees it, and its one save queue.
 *
 * Saves run one at a time, each naming the revision the previous one
 * returned, so the page never conflicts with its own writes (Admin plan,
 * *Settled requirements*). A conflict stops the queue: nothing is retried
 * with a new revision and an old patch, and editing stays off until the
 * seller reloads. Saved appears only after the server says so.
 */
export function useShopSettings() {
  const [shop, setShop] = useState<ShopSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [status, setStatus] = useState<SaveStatus>({ kind: "idle" });
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const revision = useRef<string | null>(null);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const waiting = useRef(0);
  const conflicted = useRef(false);

  const adopt = useCallback((loaded: ShopSettings) => {
    revision.current = loaded.revision;
    conflicted.current = false;
    setShop(loaded);
    setLoadError(null);
    setFieldErrors({});
    setStatus({ kind: "idle" });
  }, []);
  const refuse = useCallback((error: unknown) => {
    setLoadError(error instanceof Error ? error.message : "could not read shop.yaml");
  }, []);
  const load = useCallback(() => getShop().then(adopt, refuse), [adopt, refuse]);

  useEffect(() => {
    getShop().then(adopt, refuse);
  }, [adopt, refuse]);

  const save = useCallback((changes: ShopChanges): Promise<SaveOutcome | null> => {
    waiting.current += 1;
    setStatus({ kind: "saving" });
    const run = async (): Promise<SaveOutcome | null> => {
      try {
        if (conflicted.current || revision.current === null) return null;
        const outcome = await saveShop(revision.current, changes);
        if (outcome.kind === "saved") {
          revision.current = outcome.shop.revision;
          setShop(outcome.shop);
          setFieldErrors(
            (errors) =>
              Object.fromEntries(
                Object.entries(errors).filter(([field]) => !(field in changes)),
              ) as FieldErrors,
          );
          if (waiting.current === 1) setStatus({ kind: "saved" });
        } else if (outcome.kind === "conflict") {
          conflicted.current = true;
          setStatus({ kind: "conflict", message: outcome.message });
        } else {
          setFieldErrors((errors) => ({ ...errors, ...outcome.fieldErrors }));
          setStatus({ kind: "error", message: "Not saved" });
        }
        return outcome;
      } catch (error) {
        setStatus({
          kind: "error",
          message: error instanceof Error ? error.message : "could not save shop.yaml",
        });
        throw error;
      } finally {
        waiting.current -= 1;
      }
    };
    const next = queue.current.then(run, run);
    queue.current = next.catch(() => undefined);
    return next;
  }, []);

  return {
    shop,
    loadError,
    status,
    fieldErrors,
    save,
    reload: load,
    locked: status.kind === "conflict",
  };
}
