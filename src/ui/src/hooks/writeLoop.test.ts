import { describe, expect, it } from "vitest";
import { deferred, type Deferred } from "../test/helpers";
import { ManualClock, turns } from "../test/manualClock";
import { AUTOSAVE_DEBOUNCE_MS, type Settled, WRITTEN, WriteLoop } from "./writeLoop";

/** A disk reached over a transport whose every write the test answers. */
function harness(options: { due?: () => void } = {}) {
  const clock = new ManualClock();
  const sent: string[] = [];
  const writes: Deferred<Settled>[] = [];
  const failures: unknown[] = [];
  const loop = new WriteLoop<string>({
    send: (edit) => {
      sent.push(edit);
      const write = deferred<Settled>();
      writes.push(write);
      return write.promise;
    },
    merge: (older, newer) => `${older}+${newer}`,
    failed: (error) => {
      failures.push(error);
      return "the save failed";
    },
    clock,
    ...options,
  });
  return {
    clock,
    sent,
    failures,
    loop,
    /** Answers the oldest write not yet answered. */
    answer: async (settled: Settled = WRITTEN) => {
      writes.shift()?.resolve(settled);
      await turns();
    },
    reject: async (error: unknown) => {
      writes.shift()?.reject(error);
      await turns();
    },
  };
}

const REFUSED: Settled = { written: false, message: "a colour is missing" };

async function hasSettled(promise: Promise<unknown>): Promise<boolean> {
  let settled = false;
  void promise.then(() => (settled = true));
  await turns();
  return settled;
}

describe("the debounce", () => {
  it("sends once the last edit has been idle for the interval", () => {
    const { loop, clock, sent } = harness();

    loop.edit("a");
    clock.advance(AUTOSAVE_DEBOUNCE_MS - 1);
    loop.edit("b");
    clock.advance(AUTOSAVE_DEBOUNCE_MS - 1);
    expect(sent).toEqual([]);

    clock.advance(1);
    expect(sent).toEqual(["a+b"]);
  });

  it("is cut short by a flush, which does not fire again later", () => {
    const { loop, clock, sent } = harness();

    loop.edit("a");
    void loop.flush();
    clock.advance(AUTOSAVE_DEBOUNCE_MS);

    expect(sent).toEqual(["a"]);
  });

  it("asks its owner when it runs out, and sends nothing until told", () => {
    let due = 0;
    const { loop, clock, sent } = harness({ due: () => (due += 1) });

    loop.edit("a");
    expect(loop.armed).toBe(true);
    clock.advance(AUTOSAVE_DEBOUNCE_MS);

    expect(due).toBe(1);
    expect(loop.armed).toBe(false);
    expect(sent).toEqual([]);
    expect(loop.held).toBe("a");
  });
});

describe("one write at a time", () => {
  it("starts a write in the same turn as the flush", () => {
    const { loop, sent } = harness();

    loop.edit("a");
    void loop.flush();

    expect(sent).toEqual(["a"]);
  });

  it("holds an edit made during a write until that write answers", async () => {
    const { loop, sent, answer } = harness();

    loop.edit("a");
    void loop.flush();
    loop.edit("b");
    void loop.flush();
    expect(sent).toEqual(["a"]);

    await answer();
    expect(sent).toEqual(["a", "b"]);
  });

  it("collapses a burst of flushes into one write of the latest edit", async () => {
    const { loop, sent, answer } = harness();

    loop.edit("a");
    void loop.flush();
    loop.edit("b");
    void loop.flush();
    loop.edit("c");
    void loop.flush();
    await answer();
    await answer();

    expect(sent).toEqual(["a", "b+c"]);
  });

  it("sends nothing when nothing is held", async () => {
    const { loop, sent } = harness();

    await expect(loop.flush()).resolves.toEqual(WRITTEN);

    expect(sent).toEqual([]);
  });

  it("leaves an edit made during a write to its own debounce", async () => {
    const { loop, clock, sent, answer } = harness();

    loop.edit("a");
    void loop.flush();
    loop.edit("b");
    await answer();
    expect(sent).toEqual(["a"]);

    clock.advance(AUTOSAVE_DEBOUNCE_MS);
    expect(sent).toEqual(["a", "b"]);
  });
});

describe("keeping an edit that was not written", () => {
  it("holds a refused edit, and does not retry on its own", async () => {
    const { loop, clock, sent, answer } = harness();

    loop.edit("a");
    void loop.flush();
    await answer(REFUSED);
    clock.advance(AUTOSAVE_DEBOUNCE_MS * 10);

    expect(sent).toEqual(["a"]);
    expect(loop.held).toBe("a");
  });

  it("holds an edit whose write rejected, and reports the rejection", async () => {
    const { loop, failures, reject } = harness();
    const error = new Error("500");

    loop.edit("a");
    void loop.flush();
    await reject(error);

    expect(loop.held).toBe("a");
    expect(failures).toEqual([error]);
  });

  it("puts it under anything newer, so the newer value wins", async () => {
    const { loop, answer } = harness();

    loop.edit("a");
    void loop.flush();
    loop.edit("b");
    await answer(REFUSED);

    expect(loop.held).toBe("a+b");
  });

  it("sends it again on the next flush", async () => {
    const { loop, sent, answer } = harness();

    loop.edit("a");
    void loop.flush();
    await answer(REFUSED);
    void loop.flush();

    expect(sent).toEqual(["a", "a"]);
  });

  it("sends it with the next edit", async () => {
    const { loop, clock, sent, answer } = harness();

    loop.edit("a");
    void loop.flush();
    await answer(REFUSED);
    loop.edit("b");
    clock.advance(AUTOSAVE_DEBOUNCE_MS);

    expect(sent).toEqual(["a", "a+b"]);
  });

  it("retries once when a flush was waiting behind the failed write", async () => {
    const { loop, sent, answer } = harness();

    loop.edit("a");
    void loop.flush();
    loop.edit("b");
    void loop.flush();
    await answer(REFUSED);
    expect(sent).toEqual(["a", "a+b"]);

    await answer(REFUSED);
    expect(sent).toEqual(["a", "a+b"]);
  });

  it("forgets what is held when discarded, while a write out finishes", async () => {
    const { loop, clock, sent, answer } = harness();

    loop.edit("a");
    const out = loop.flush();
    loop.edit("b");
    loop.discard();
    clock.advance(AUTOSAVE_DEBOUNCE_MS);
    await answer();

    expect(sent).toEqual(["a"]);
    expect(await out).toEqual(WRITTEN);
  });
});

describe("what a flush reports", () => {
  it("resolves only once the write it asked for has landed", async () => {
    const { loop, answer } = harness();

    loop.edit("a");
    const settled = loop.flush();
    expect(await hasSettled(settled)).toBe(false);

    await answer();
    await expect(settled).resolves.toEqual(WRITTEN);
  });

  it("waits for a write already out when nothing more is held", async () => {
    const { loop, clock, answer } = harness();

    loop.edit("a");
    clock.advance(AUTOSAVE_DEBOUNCE_MS);
    const settled = loop.flush();
    expect(await hasSettled(settled)).toBe(false);

    await answer();
    await expect(settled).resolves.toEqual(WRITTEN);
  });

  it("waits for an edit queued behind a write out", async () => {
    const { loop, answer } = harness();

    loop.edit("a");
    void loop.flush();
    loop.edit("b");
    const settled = loop.flush();
    await answer();
    expect(await hasSettled(settled)).toBe(false);

    await answer();
    await expect(settled).resolves.toEqual(WRITTEN);
  });

  it("does not wait for an edit made after the last write began", async () => {
    const { loop, answer } = harness();

    loop.edit("a");
    const settled = loop.flush();
    loop.edit("b");
    await answer();

    await expect(settled).resolves.toEqual(WRITTEN);
    expect(loop.held).toBe("b");
  });

  it("says why when the server refused", async () => {
    const { loop, answer } = harness();

    loop.edit("a");
    const settled = loop.flush();
    await answer(REFUSED);

    await expect(settled).resolves.toEqual(REFUSED);
  });

  it("resolves with the failure when a write rejects, never rejecting", async () => {
    const { loop, reject } = harness();

    loop.edit("a");
    const settled = loop.flush();
    await reject(new Error("500"));

    await expect(settled).resolves.toEqual({ written: false, message: "the save failed" });
  });

  it("reports the retry when a flush behind a failed write made one", async () => {
    const { loop, answer } = harness();

    loop.edit("a");
    void loop.flush();
    const settled = loop.flush();
    await answer(REFUSED);
    await answer();

    await expect(settled).resolves.toEqual(WRITTEN);
  });

  it("starts a fresh drain for a flush after the last one finished", async () => {
    const { loop, sent, answer } = harness();

    loop.edit("a");
    void loop.flush();
    await answer();
    loop.edit("b");
    const settled = loop.flush();
    await answer();

    expect(sent).toEqual(["a", "b"]);
    await expect(settled).resolves.toEqual(WRITTEN);
  });
});

describe("a task after the write", () => {
  it("runs once everything held is written", async () => {
    const { loop, answer } = harness();
    const ran: string[] = [];

    loop.edit("a");
    void loop.afterWrite(async () => {
      ran.push("task");
    });
    expect(ran).toEqual([]);
    await answer();

    expect(ran).toEqual(["task"]);
  });

  it("waits for a write already out", async () => {
    const { loop, clock, answer } = harness();
    const ran: string[] = [];

    loop.edit("a");
    clock.advance(AUTOSAVE_DEBOUNCE_MS);
    void loop.afterWrite(async () => {
      ran.push("task");
    });
    await turns();
    expect(ran).toEqual([]);

    await answer();
    expect(ran).toEqual(["task"]);
  });

  it("does not run when the edit was refused, and says why", async () => {
    const { loop, answer } = harness();
    const ran: string[] = [];

    loop.edit("a");
    const settled = loop.afterWrite(async () => {
      ran.push("task");
    });
    await answer(REFUSED);

    await expect(settled).resolves.toEqual(REFUSED);
    expect(ran).toEqual([]);
    expect(loop.held).toBe("a");
  });

  it("holds edits made during it, and sends them after", async () => {
    const { loop, clock, sent, answer } = harness();
    const task = deferred<undefined>();

    const settled = loop.afterWrite(() => task.promise);
    loop.edit("a");
    clock.advance(AUTOSAVE_DEBOUNCE_MS);
    await turns();
    expect(sent).toEqual([]);

    task.resolve(undefined);
    await turns();
    expect(sent).toEqual(["a"]);
    await answer();
    await expect(settled).resolves.toEqual(WRITTEN);
  });

  it("keeps a flush waiting until it ends", async () => {
    const { loop } = harness();
    const task = deferred<undefined>();

    void loop.afterWrite(() => task.promise);
    const settled = loop.flush();
    expect(await hasSettled(settled)).toBe(false);

    task.resolve(undefined);
    await expect(settled).resolves.toEqual(WRITTEN);
  });

  it("reports a task that rejects, never rejecting", async () => {
    const { loop, failures } = harness();
    const error = new Error("boom");

    await expect(loop.afterWrite(() => Promise.reject(error))).resolves.toEqual({
      written: false,
      message: "the save failed",
    });
    expect(failures).toEqual([error]);
  });
});
