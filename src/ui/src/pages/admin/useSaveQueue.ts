import { useCallback, useEffect, useRef, useState } from "react";

export type SaveStatus =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved" }
  | { kind: "error"; message: string }
  | { kind: "conflict"; message: string };

export type SaveOutcome =
  | { kind: "saved"; revision: string }
  | { kind: "stale"; message: string }
  | { kind: "refused"; message: string; fieldErrors: FieldErrors };

export type FieldErrors = Partial<Record<string, string>>;
export type RefusedValue<T> = { value: T; attempt: number };

type Changes = Record<string, unknown>;

/** The value a key's newest save carried, and why it failed. */
type RetainedFailure = { value: unknown; message: string; refusal: number | null };

const ignore = () => undefined;

/**
 * `save` resolves `null` when a conflict skipped it and rejects when the
 * request failed. A caller that reports and retries its own failure saves
 * with `retain: false`.
 */
export function useSaveQueue<C extends Changes, O extends SaveOutcome>({
  send,
  answersError,
  fallbackMessage,
  onSaved,
}: {
  send: (revision: string, changes: C) => Promise<O>;
  onSaved?: (outcome: Extract<O, { kind: "saved" }>) => void;
  /** Also called with a single-key patch, to attribute a refusal to that change. */
  answersError: (errorKey: string, changes: C) => boolean;
  fallbackMessage: string;
}) {
  const [status, setStatus] = useState<SaveStatus>({ kind: "idle" });
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [pending, setPending] = useState<Partial<C>>({});
  const adopt = useRef(onSaved);
  useEffect(() => {
    adopt.current = onSaved;
  });
  const revision = useRef<string | null>(null);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const waiting = useRef(0);
  const conflicted = useRef(false);
  const sequence = useRef(0);
  const newestSaveByKey = useRef(new Map<string, number>());
  const failedByKey = useRef(new Map<string, RetainedFailure>());
  const acknowledged = useRef(false);

  const settle = useCallback((remaining: number) => {
    if (conflicted.current) return;
    const outstanding = [...failedByKey.current.values()].pop();
    setStatus(settledStatus(outstanding?.message, remaining, acknowledged.current));
  }, []);

  const reset = useCallback((loaded: string) => {
    revision.current = loaded;
    conflicted.current = false;
    newestSaveByKey.current = new Map();
    failedByKey.current = new Map();
    acknowledged.current = false;
    setPending({});
    setFieldErrors({});
    setStatus({ kind: "idle" });
  }, []);

  const afterSaves = useCallback(<T>(next: () => Promise<T>) => queue.current.then(next), []);

  const refusal = useCallback(<K extends keyof C & string>(field: K): RefusedValue<C[K]> | null => {
    const held = failedByKey.current.get(field);
    return held && held.refusal !== null
      ? { value: held.value as C[K], attempt: held.refusal }
      : null;
  }, []);

  const discard = useCallback(
    (changes: C) => {
      if (conflicted.current) return;
      for (const key of Object.keys(changes)) failedByKey.current.delete(key);
      setFieldErrors((errors) =>
        Object.fromEntries(Object.entries(errors).filter(([key]) => !answersError(key, changes))),
      );
      settle(waiting.current);
    },
    [answersError, settle],
  );

  const save = useCallback(
    (changes: C, { retain = true }: { retain?: boolean } = {}): Promise<O | null> => {
      if (conflicted.current) return Promise.resolve(null);
      const mine = ++sequence.current;
      for (const key of Object.keys(changes)) {
        newestSaveByKey.current.set(key, mine);
        failedByKey.current.delete(key);
      }
      setPending((held) => ({ ...held, ...changes }));
      const answered = () => {
        const keys = Object.keys(changes).filter(
          (key) => newestSaveByKey.current.get(key) === mine,
        );
        setPending(
          (held) =>
            Object.fromEntries(
              Object.entries(held).filter(([key]) => !keys.includes(key)),
            ) as Partial<C>,
        );
      };
      const fail = (message: string, errors: FieldErrors = {}) => {
        const each = Object.entries(changes).map(([key, value]) => ({
          current: newestSaveByKey.current.get(key) === mine,
          changed: { [key]: value } as C,
        }));
        if (!retain || !each.some(({ current }) => current)) {
          settle(waiting.current - 1);
          return;
        }
        const stale = (field: string) =>
          each.some(({ changed }) => answersError(field, changed)) &&
          !each.some(({ current, changed }) => current && answersError(field, changed));
        setFieldErrors((held) => ({
          ...held,
          ...Object.fromEntries(Object.entries(errors).filter(([field]) => !stale(field))),
        }));
        const refusedFields = Object.keys(errors);
        for (const [key, value] of Object.entries(changes)) {
          if (newestSaveByKey.current.get(key) !== mine) continue;
          const changed = { [key]: value } as C;
          const refused = refusedFields.some((field) => answersError(field, changed));
          failedByKey.current.set(key, { value, message, refusal: refused ? mine : null });
        }
        acknowledged.current = false;
        setStatus({ kind: "error", message });
      };
      waiting.current += 1;
      setStatus({ kind: "saving" });

      const run = async (): Promise<O | null> => {
        try {
          if (conflicted.current || revision.current === null) return null;
          const outcome = await send(revision.current, changes);
          if (outcome.kind === "saved") {
            acknowledged.current = true;
            revision.current = outcome.revision;
            adopt.current?.(outcome as Extract<O, { kind: "saved" }>);
            setFieldErrors((errors) =>
              Object.fromEntries(
                Object.entries(errors).filter(([key]) => !answersError(key, changes)),
              ),
            );
            if (waiting.current === 1) settle(0);
          } else if (outcome.kind === "stale") {
            conflicted.current = true;
            setStatus({ kind: "conflict", message: outcome.message });
          } else {
            fail(outcome.fieldErrors.__root__ ?? "Not saved", outcome.fieldErrors);
          }
          return outcome;
        } catch (error) {
          fail(error instanceof Error ? error.message : fallbackMessage);
          throw error;
        } finally {
          answered();
          waiting.current -= 1;
        }
      };
      const next = queue.current.then(run, run);
      queue.current = next.catch(() => undefined);
      return next;
    },
    [send, answersError, fallbackMessage, settle],
  );

  const retry = useCallback(() => {
    if (!failedByKey.current.size) return Promise.resolve(null);
    const changes = Object.fromEntries(
      [...failedByKey.current].map(([key, { value }]) => [key, value]),
    ) as C;
    return save(changes);
  }, [save]);

  /** `status` reports what these fail with, so they never reject. */
  const queueSave = useCallback((changes: C) => void save(changes).catch(ignore), [save]);
  const queueRetry = useCallback(() => void retry().catch(ignore), [retry]);

  /** Runs after every queued save, naming the revision they left. */
  const writeOutside = useCallback(
    <T>(write: (revision: string) => Promise<T>) => afterSaves(() => write(revision.current ?? "")),
    [afterSaves],
  );

  return {
    status,
    fieldErrors,
    pending,
    save,
    discard,
    refusal,
    retry,
    reset,
    queueSave,
    queueRetry,
    afterSaves,
    writeOutside,
    locked: status.kind === "conflict",
  };
}

function settledStatus(
  failure: string | undefined,
  remaining: number,
  acknowledged: boolean,
): SaveStatus {
  if (failure !== undefined) return { kind: "error", message: failure };
  if (remaining > 0) return { kind: "saving" };
  return acknowledged ? { kind: "saved" } : { kind: "idle" };
}
