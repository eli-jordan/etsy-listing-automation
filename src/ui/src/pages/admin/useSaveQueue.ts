import { useCallback, useEffect, useRef, useState } from "react";

export type SaveStatus =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved" }
  | { kind: "error"; message: string }
  | { kind: "conflict"; message: string };

/** What a file's save endpoint answers; `saved` carries the revision the
 * next save must name. */
export type SaveOutcome =
  | { kind: "saved"; revision: string }
  | { kind: "conflict"; message: string }
  | { kind: "invalid"; message: string; fieldErrors: FieldErrors };

export type FieldErrors = Partial<Record<string, string>>;
export type RefusedValue<T> = { value: T; attempt: number };

type Changes = Record<string, unknown>;

/**
 * One revisioned file's save queue, shared by Shop and Settings (Admin
 * interactions, *Invalid files and conflicting saves*). Each panel keeps its
 * own editing rules; this owns what both must agree on:
 *
 * - Saves run one at a time, each naming the revision the previous one
 *   returned, so the page never conflicts with its own writes.
 * - Every change key is tracked until a response acknowledges it. A failed
 *   or refused key stays failed until a later save of that key succeeds: an
 *   unrelated success never reports Saved over it, and Retry sends exactly
 *   the failed keys. A newer save or an explicit unchanged choice supersedes
 *   that key's failure; `discard` never cancels queued writes.
 * - A conflict stops the queue. Nothing is retried with a new revision and an
 *   old patch; editing stays off until `reset` adopts a reloaded file.
 * - `pending` holds each key's newest unanswered value, whether a field save
 *   or Retry sent it: what the file will hold once the queue drains, so a
 *   control compares a newer choice with that rather than the last answer.
 *   A key leaves `pending` in the same update as `onSaved` adopts its answer.
 *
 * `save` resolves with the outcome, `null` when a conflict skipped it, and
 * rejects when the request itself failed. A caller that reports its own
 * failure and retries through its own acknowledged action, like the currency
 * dialog, saves with `retain: false`: its failure is neither kept for Retry
 * nor allowed to hold Saved back once the seller abandons it.
 */
export function useSaveQueue<C extends Changes, O extends SaveOutcome>({
  send,
  clears,
  fallback,
  onSaved,
}: {
  send: (revision: string, changes: C) => Promise<O>;
  /** Adopts a successful answer's values, whichever save sent it. */
  onSaved?: (outcome: Extract<O, { kind: "saved" }>) => void;
  /** Whether `changes` answers the error at `key`. Also called with a
   * single-key patch to attribute a validation refusal to that change. */
  clears: (key: string, changes: C) => boolean;
  /** The status message for a failure that brought none. */
  fallback: string;
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
  /** The sequence of the newest save of each key. */
  const latest = useRef(new Map<string, number>());
  /** Keys whose newest save failed: the value it carried and why. */
  const failed = useRef(
    new Map<string, { value: unknown; message: string; refusal: number | null }>(),
  );
  const acknowledged = useRef(false);

  const settle = useCallback((remaining: number) => {
    if (conflicted.current) return;
    const outstanding = [...failed.current.values()].pop();
    setStatus(settledStatus(outstanding?.message, remaining, acknowledged.current));
  }, []);

  const reset = useCallback((loaded: string) => {
    revision.current = loaded;
    conflicted.current = false;
    latest.current = new Map();
    failed.current = new Map();
    acknowledged.current = false;
    setPending({});
    setFieldErrors({});
    setStatus({ kind: "idle" });
  }, []);

  const afterSaves = useCallback(<T>(next: () => Promise<T>) => queue.current.then(next), []);

  /** The latest refused value for a key, whichever save (including Retry)
   * sent it. A new attempt, discard or reload supersedes this refusal. */
  const refusal = useCallback(<K extends keyof C & string>(field: K): RefusedValue<C[K]> | null => {
    const held = failed.current.get(field);
    return held && held.refusal !== null
      ? { value: held.value as C[K], attempt: held.refusal }
      : null;
  }, []);

  /** Choosing what the file will already hold abandons only that field's
   * failed patch. It never cancels a queued write or acknowledges a save. */
  const discard = useCallback(
    (changes: C) => {
      if (conflicted.current) return;
      for (const key of Object.keys(changes)) failed.current.delete(key);
      setFieldErrors((errors) =>
        Object.fromEntries(Object.entries(errors).filter(([key]) => !clears(key, changes))),
      );
      settle(waiting.current);
    },
    [clears, settle],
  );

  const save = useCallback(
    (changes: C, { retain = true }: { retain?: boolean } = {}): Promise<O | null> => {
      if (conflicted.current) return Promise.resolve(null);
      const mine = ++sequence.current;
      for (const key of Object.keys(changes)) {
        latest.current.set(key, mine);
        failed.current.delete(key);
      }
      setPending((held) => ({ ...held, ...changes }));
      const answered = () => {
        const keys = Object.keys(changes).filter((key) => latest.current.get(key) === mine);
        setPending(
          (held) =>
            Object.fromEntries(
              Object.entries(held).filter(([key]) => !keys.includes(key)),
            ) as Partial<C>,
        );
      };
      const fail = (message: string, errors: FieldErrors = {}) => {
        const each = Object.entries(changes).map(([key, value]) => ({
          current: latest.current.get(key) === mine,
          changed: { [key]: value } as C,
        }));
        if (!retain || !each.some(({ current }) => current)) {
          // The caller reports this failure itself and owns its retry, or a
          // newer save of every key will answer instead; the page goes back
          // to what the retained failures and queue say.
          settle(waiting.current - 1);
          return;
        }
        // An error only about keys a newer save carries belongs to a value
        // the seller has already replaced.
        const stale = (field: string) =>
          each.some(({ changed }) => clears(field, changed)) &&
          !each.some(({ current, changed }) => current && clears(field, changed));
        setFieldErrors((held) => ({
          ...held,
          ...Object.fromEntries(Object.entries(errors).filter(([field]) => !stale(field))),
        }));
        const refusedFields = Object.keys(errors);
        for (const [key, value] of Object.entries(changes)) {
          if (latest.current.get(key) !== mine) continue;
          // Unnamed changes were not written, but their values were not
          // refused. Keep them retryable independently of the bad field.
          const changed = { [key]: value } as C;
          const refused = refusedFields.some((field) => clears(field, changed));
          failed.current.set(key, { value, message, refusal: refused ? mine : null });
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
              Object.fromEntries(Object.entries(errors).filter(([key]) => !clears(key, changes))),
            );
            if (waiting.current === 1) settle(0);
          } else if (outcome.kind === "conflict") {
            conflicted.current = true;
            setStatus({ kind: "conflict", message: outcome.message });
          } else {
            // Document errors have no field control to show their reason.
            // Retain it with the failed patch through sibling saves and Retry.
            fail(outcome.fieldErrors.__root__ ?? "Not saved", outcome.fieldErrors);
          }
          return outcome;
        } catch (error) {
          fail(error instanceof Error ? error.message : fallback);
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
    [send, clears, fallback, settle],
  );

  const retry = useCallback(() => {
    if (!failed.current.size) return Promise.resolve(null);
    const changes = Object.fromEntries(
      [...failed.current].map(([key, { value }]) => [key, value]),
    ) as C;
    return save(changes);
  }, [save]);

  return {
    status,
    fieldErrors,
    pending,
    save,
    discard,
    refusal,
    retry,
    reset,
    afterSaves,
    locked: status.kind === "conflict",
  };
}

/** The queue's status once a save settles: an outstanding failure wins, then pending saves. */
function settledStatus(
  failure: string | undefined,
  remaining: number,
  acknowledged: boolean,
): SaveStatus {
  if (failure !== undefined) return { kind: "error", message: failure };
  if (remaining > 0) return { kind: "saving" };
  return acknowledged ? { kind: "saved" } : { kind: "idle" };
}
