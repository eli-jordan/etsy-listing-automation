import { useCallback, useRef, useState } from "react";

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
 *   the failed keys. A newer save of a key supersedes its failure.
 * - A conflict stops the queue. Nothing is retried with a new revision and an
 *   old patch; editing stays off until `reset` adopts a reloaded file.
 *
 * `save` resolves with the outcome, `null` when a conflict skipped it, and
 * rejects when the request itself failed.
 */
export function useSaveQueue<C extends Changes, O extends SaveOutcome>({
  send,
  clears,
  fallback,
}: {
  send: (revision: string, changes: C) => Promise<O>;
  /** Whether a successful save of `changes` answers the field error at `key`. */
  clears: (key: string, changes: C) => boolean;
  /** The status message for a failure that brought none. */
  fallback: string;
}) {
  const [status, setStatus] = useState<SaveStatus>({ kind: "idle" });
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const revision = useRef<string | null>(null);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const waiting = useRef(0);
  const conflicted = useRef(false);
  const sequence = useRef(0);
  /** The sequence of the newest save of each key. */
  const latest = useRef(new Map<string, number>());
  /** Keys whose newest save failed: the value it carried and why. */
  const failed = useRef(new Map<string, { value: unknown; message: string }>());

  const reset = useCallback((loaded: string) => {
    revision.current = loaded;
    conflicted.current = false;
    latest.current = new Map();
    failed.current = new Map();
    setFieldErrors({});
    setStatus({ kind: "idle" });
  }, []);

  const afterSaves = useCallback(<T>(next: () => Promise<T>) => queue.current.then(next), []);

  const save = useCallback(
    (changes: C): Promise<O | null> => {
      if (conflicted.current) return Promise.resolve(null);
      const mine = ++sequence.current;
      for (const key of Object.keys(changes)) {
        latest.current.set(key, mine);
        failed.current.delete(key);
      }
      const fail = (message: string) => {
        for (const [key, value] of Object.entries(changes))
          if (latest.current.get(key) === mine) failed.current.set(key, { value, message });
        setStatus({ kind: "error", message });
      };
      waiting.current += 1;
      setStatus({ kind: "saving" });

      const run = async (): Promise<O | null> => {
        try {
          if (conflicted.current || revision.current === null) return null;
          const outcome = await send(revision.current, changes);
          if (outcome.kind === "saved") {
            revision.current = outcome.revision;
            setFieldErrors((errors) =>
              Object.fromEntries(Object.entries(errors).filter(([key]) => !clears(key, changes))),
            );
            const outstanding = [...failed.current.values()].pop();
            if (waiting.current === 1)
              setStatus(
                outstanding ? { kind: "error", message: outstanding.message } : { kind: "saved" },
              );
          } else if (outcome.kind === "conflict") {
            conflicted.current = true;
            setStatus({ kind: "conflict", message: outcome.message });
          } else {
            setFieldErrors((errors) => ({ ...errors, ...outcome.fieldErrors }));
            fail("Not saved");
          }
          return outcome;
        } catch (error) {
          fail(error instanceof Error ? error.message : fallback);
          throw error;
        } finally {
          waiting.current -= 1;
        }
      };
      const next = queue.current.then(run, run);
      queue.current = next.catch(() => undefined);
      return next;
    },
    [send, clears, fallback],
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
    save,
    retry,
    reset,
    afterSaves,
    locked: status.kind === "conflict",
  };
}
