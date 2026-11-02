import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { type SaveOutcome, useSaveQueue } from "./useSaveQueue";

/* The save queue Shop and Settings share, through its own interface: the
   endpoint is a script the test answers one request at a time, so ordering,
   revisions and every failure kind are observable without a page. */

type Changes = Record<string, unknown>;
type Request = {
  revision: string;
  changes: Changes;
  answer: (outcome: SaveOutcome) => Promise<void>;
  fail: (message: string) => Promise<void>;
};

const SAVED = (revision: string): SaveOutcome => ({ kind: "saved", revision });

function nth(requests: Request[], index: number): Request {
  const request = requests[index];
  if (!request) throw new Error(`request ${index} was never sent`);
  return request;
}

function mount() {
  const requests: Request[] = [];
  const send = vi.fn(
    (revision: string, changes: Changes) =>
      new Promise<SaveOutcome>((resolve, reject) => {
        requests.push({
          revision,
          changes,
          answer: (outcome) => act(async () => resolve(outcome)),
          fail: (message) => act(async () => reject(new Error(message))),
        });
      }),
  );
  const onSaved = vi.fn();
  // A field's error is answered by a patch that carries that field.
  const clears = (key: string, changes: Changes) => key in changes;
  const hook = renderHook(() =>
    useSaveQueue({ send, clears, fallback: "could not save", onSaved }),
  );
  act(() => hook.result.current.reset("r1"));

  const queue = () => hook.result.current;
  return {
    queue,
    requests,
    send,
    onSaved,
    /** Saves as a control would; a failed request's rejection is the caller's to ignore. */
    save(changes: Changes, options?: { retain?: boolean }) {
      let saved!: Promise<SaveOutcome | null>;
      act(() => {
        saved = queue().save(changes, options);
      });
      saved.catch(() => undefined);
      return saved;
    },
    retry() {
      let retried!: Promise<SaveOutcome | null>;
      act(() => {
        retried = queue().retry();
      });
      return retried;
    },
    /** Waits until the queue has sent `count` requests in all. */
    sent: (count: number) => waitFor(() => expect(requests).toHaveLength(count)),
  };
}

describe("useSaveQueue", () => {
  it("sends one save at a time, each naming the revision the previous answer carried", async () => {
    const { save, requests, sent, queue, onSaved } = mount();
    save({ renewal: "auto" });
    save({ who_made: "collective" });
    await sent(1);
    expect(queue().status).toEqual({ kind: "saving" });

    await nth(requests, 0).answer(SAVED("r2"));
    await sent(2);
    expect(requests.map(({ revision, changes }) => [revision, changes])).toEqual([
      ["r1", { renewal: "auto" }],
      ["r2", { who_made: "collective" }],
    ]);
    expect(queue().status).toEqual({ kind: "saving" });

    await nth(requests, 1).answer(SAVED("r3"));
    expect(queue().status).toEqual({ kind: "saved" });
    expect(onSaved.mock.calls.map(([outcome]) => outcome.revision)).toEqual(["r2", "r3"]);
  });

  it("holds a key's newest unanswered value as pending until that save is answered", async () => {
    const { save, requests, sent, queue } = mount();
    save({ renewal: "auto" });
    save({ renewal: "manual" });
    expect(queue().pending).toEqual({ renewal: "manual" });

    await sent(1);
    await nth(requests, 0).answer(SAVED("r2"));
    expect(queue().pending).toEqual({ renewal: "manual" });

    await sent(2);
    await nth(requests, 1).answer(SAVED("r3"));
    expect(queue().pending).toEqual({});
  });

  it("keeps a failed key failed through a sibling's success and retries exactly that key", async () => {
    const { save, retry, requests, sent, queue } = mount();
    save({ renewal: "auto" });
    await sent(1);
    await nth(requests, 0).fail("network down");
    expect(queue().status).toEqual({ kind: "error", message: "network down" });

    save({ who_made: "collective" });
    await sent(2);
    await nth(requests, 1).answer(SAVED("r2"));
    expect(queue().status).toEqual({ kind: "error", message: "network down" });

    retry();
    await sent(3);
    // The failed request wrote nothing; the retry names the sibling's revision.
    expect(requests[2]).toMatchObject({ revision: "r2", changes: { renewal: "auto" } });
    await nth(requests, 2).answer(SAVED("r3"));
    expect(queue().status).toEqual({ kind: "saved" });
  });

  it("lets a newer save of a failed key supersede its failure", async () => {
    const { save, retry, requests, sent, queue, send } = mount();
    save({ renewal: "auto" });
    await sent(1);
    await nth(requests, 0).fail("network down");

    save({ renewal: "manual" });
    await sent(2);
    await nth(requests, 1).answer(SAVED("r2"));
    expect(queue().status).toEqual({ kind: "saved" });
    await expect(retry()).resolves.toBeNull();
    expect(send).toHaveBeenCalledTimes(2);
  });

  it("discards only a key's failure and never cancels a queued write", async () => {
    const { save, retry, requests, sent, queue } = mount();
    save({ renewal: "auto" });
    await sent(1);
    await nth(requests, 0).fail("network down");
    save({ who_made: "collective" });

    act(() => queue().discard({ renewal: "manual" }));
    expect(queue().status).toEqual({ kind: "saving" });

    await sent(2);
    await nth(requests, 1).answer(SAVED("r2"));
    expect(queue().status).toEqual({ kind: "saved" });
    await expect(retry()).resolves.toBeNull();
    expect(requests).toHaveLength(2);
  });

  it("keeps a refused value and its field error until a later save of that key", async () => {
    const { save, requests, sent, queue } = mount();
    const refused = save({ renewal: "yearly" });
    await sent(1);
    await nth(requests, 0).answer({
      kind: "invalid",
      message: "invalid renewal",
      fieldErrors: { renewal: "Input should be 'manual' or 'auto'" },
    });
    await expect(refused).resolves.toMatchObject({ kind: "invalid" });
    expect(queue().status).toEqual({ kind: "error", message: "Not saved" });
    expect(queue().fieldErrors).toEqual({ renewal: "Input should be 'manual' or 'auto'" });
    expect(queue().refusal("renewal")).toEqual({ value: "yearly", attempt: 1 });

    save({ renewal: "auto" });
    await sent(2);
    await nth(requests, 1).answer(SAVED("r2"));
    expect(queue().fieldErrors).toEqual({});
    expect(queue().refusal("renewal")).toBeNull();
    expect(queue().status).toEqual({ kind: "saved" });
  });

  it("reports a document-level refusal as the status, since no control owns it", async () => {
    const { save, requests, sent, queue } = mount();
    save({ providers: ["codex"] });
    await sent(1);
    await nth(requests, 0).answer({
      kind: "invalid",
      message: "__root__: cannot edit",
      fieldErrors: { __root__: "Edit this value in the file, then reload Settings." },
    });
    expect(queue().status).toEqual({
      kind: "error",
      message: "Edit this value in the file, then reload Settings.",
    });
    // An unnamed change was not refused, only not written.
    expect(queue().refusal("providers")).toBeNull();
  });

  it("shows nothing for a refusal of a value a newer save has replaced", async () => {
    const { save, requests, sent, queue } = mount();
    save({ renewal: "yearly" });
    save({ renewal: "manual" });
    await sent(1);
    await nth(requests, 0).answer({
      kind: "invalid",
      message: "invalid renewal",
      fieldErrors: { renewal: "refused" },
    });
    expect(queue().fieldErrors).toEqual({});
    expect(queue().status).toEqual({ kind: "saving" });

    await sent(2);
    await nth(requests, 1).answer(SAVED("r2"));
    expect(queue().status).toEqual({ kind: "saved" });
  });

  it("stops the queue at a conflict until reset adopts a reloaded file", async () => {
    const { save, requests, sent, queue } = mount();
    save({ renewal: "auto" });
    const queued = save({ who_made: "collective" });
    await sent(1);
    await nth(requests, 0).answer({ kind: "conflict", message: "shop.yaml changed on disk" });

    await expect(queued).resolves.toBeNull();
    await expect(save({ renewal: "manual" })).resolves.toBeNull();
    expect(requests).toHaveLength(1);
    expect(queue().locked).toBe(true);
    expect(queue().status).toEqual({ kind: "conflict", message: "shop.yaml changed on disk" });

    act(() => queue().reset("r9"));
    expect(queue().locked).toBe(false);
    expect(queue().status).toEqual({ kind: "idle" });
    save({ renewal: "manual" });
    await sent(2);
    expect(requests[1]).toMatchObject({ revision: "r9", changes: { renewal: "manual" } });
  });

  it("neither retries nor reports a failure its caller retains itself", async () => {
    const { save, retry, requests, sent, queue } = mount();
    const currency = save({ currency: "EUR" }, { retain: false });
    await sent(1);
    await nth(requests, 0).fail("network down");
    await expect(currency).rejects.toThrow("network down");
    expect(queue().status).toEqual({ kind: "idle" });
    await expect(retry()).resolves.toBeNull();

    save({ renewal: "auto" });
    await sent(2);
    await nth(requests, 1).answer(SAVED("r2"));
    expect(queue().status).toEqual({ kind: "saved" });
  });

  it("runs afterSaves once every save queued before it is answered", async () => {
    const { save, requests, sent, queue } = mount();
    save({ renewal: "auto" });
    const after = vi.fn(() => Promise.resolve("reloaded"));
    const done = queue().afterSaves(after);
    await sent(1);
    expect(after).not.toHaveBeenCalled();

    await nth(requests, 0).answer(SAVED("r2"));
    await expect(done).resolves.toBe("reloaded");
  });
});
