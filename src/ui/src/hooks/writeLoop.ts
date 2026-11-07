/** How long an editor waits after the last edit before saving -- long enough
 * that a run of keystrokes in a text field collapses into one request, short
 * enough that "Saved a moment ago" reads as true. Also cut short on blur, on a
 * tab switch and on unmount, so a save is never waiting on this timer alone. */
export const AUTOSAVE_DEBOUNCE_MS = 800;

/** What a caller about to act on the file needs to know. `written` means the
 * disk holds every edit made before the flush; `written: false` means at least
 * one is still held here, and `message` says why in the seller's terms. */
export type Settled = { written: true } | { written: false; message: string };

export const WRITTEN: Settled = { written: true };

/** Time, for the debounce. `after` answers how to cancel. */
export interface Clock {
  after: (ms: number, run: () => void) => () => void;
}

const REAL_CLOCK: Clock = {
  after: (ms, run) => {
    const timer = setTimeout(run, ms);
    return () => clearTimeout(timer);
  },
};

export interface WriteLoopOptions<Edit> {
  /** Writes `edit`, which is everything held. An edit made meanwhile is held
   * for the next write. Answering `written: false`, or rejecting, gives the
   * edit back to the loop. */
  send: (edit: Edit) => Promise<Settled>;
  /** One edit standing for both. On a clash `newer` wins. */
  merge: (older: Edit, newer: Edit) => Edit;
  /** A `send` or task rejected: report it, and answer the {@link Settled}
   * message. */
  failed: (error: unknown) => string;
  /** The debounce ran out. A flush, unless the owner has a reason to wait. */
  due?: () => void;
  clock?: Clock;
}

/**
 * The one way an edit reaches the disk, for any editor that autosaves. It owns
 * the order of writes, the collapsing of edits into one write, keeping an edit
 * that was not written, and what a caller is told when the writing stops. What
 * an edit is, what a write sends and what the page shows about it are the
 * owner's, through {@link WriteLoopOptions}.
 *
 * - One write at a time, in order: whichever of two concurrent requests resolved
 *   last would win, regardless of which held the newer edit.
 * - An edit is held until it is written. A failure does not retry on its own: a
 *   metered or broken server must not see a loop. The next flush or edit does.
 * - {@link flush} sends now, resolves only when no write is out, and never
 *   rejects, because nothing on a timer or a blur could catch it.
 */
export class WriteLoop<Edit> {
  private waiting: Edit | null = null;
  private cancelDebounce: (() => void) | null = null;
  /** A flush arrived since the last write began, so another pass is owed. */
  private asked = false;
  private tasks: (() => Promise<void>)[] = [];
  private draining = false;
  private finished: Promise<Settled> = Promise.resolve(WRITTEN);
  private readonly send: WriteLoopOptions<Edit>["send"];
  private readonly merge: WriteLoopOptions<Edit>["merge"];
  private readonly failed: WriteLoopOptions<Edit>["failed"];
  private readonly due: () => void;
  private readonly clock: Clock;

  constructor(options: WriteLoopOptions<Edit>) {
    this.send = options.send;
    this.merge = options.merge;
    this.failed = options.failed;
    this.due = options.due ?? (() => void this.flush());
    this.clock = options.clock ?? REAL_CLOCK;
  }

  /** What is waiting to be written, without what is out in a write now. */
  get held(): Edit | null {
    return this.waiting;
  }

  /** The debounce is running. */
  get armed(): boolean {
    return this.cancelDebounce !== null;
  }

  /** Holds `edit` and restarts the debounce. */
  edit(edit: Edit) {
    this.waiting = this.waiting === null ? edit : this.merge(this.waiting, edit);
    this.disarm();
    this.cancelDebounce = this.clock.after(AUTOSAVE_DEBOUNCE_MS, () => {
      this.cancelDebounce = null;
      this.due();
    });
  }

  /** Sends what is held, starting synchronously if nothing is out: a page
   * being left may not get another turn. A burst of flushes shares one write
   * of the latest edit, and all of them answer for how the writing ended. An
   * edit made after the last write began is not waited for. */
  flush(): Promise<Settled> {
    this.disarm();
    this.asked = true;
    if (!this.draining) {
      this.draining = true;
      this.finished = this.drain();
    }
    return this.finished;
  }

  /** Flushes, then runs `task` if everything was written; if not, `task` never
   * runs. No write goes out during it: edits wait, and go after it, so a task
   * can change where they go. Answers as {@link flush} does. */
  afterWrite(task: () => Promise<void>): Promise<Settled> {
    this.tasks.push(task);
    return this.flush();
  }

  /** Drops what is held. A write already out finishes. */
  discard() {
    this.disarm();
    this.waiting = null;
  }

  private disarm() {
    this.cancelDebounce?.();
    this.cancelDebounce = null;
  }

  private async drain(): Promise<Settled> {
    let settled = WRITTEN;
    for (;;) {
      if (this.asked) {
        this.asked = false;
        if (this.waiting !== null) settled = await this.write(this.waiting);
        continue;
      }
      const task = this.tasks.shift();
      if (task === undefined) break;
      if (settled.written) settled = await this.attempt(() => task().then(() => WRITTEN));
    }
    // In the same turn as the check above, or a flush could join a drain that
    // has already looked for work.
    this.draining = false;
    return settled;
  }

  private async write(edit: Edit): Promise<Settled> {
    this.waiting = null;
    const settled = await this.attempt(() => this.send(edit));
    if (!settled.written) {
      this.waiting = this.waiting === null ? edit : this.merge(edit, this.waiting);
    }
    return settled;
  }

  private async attempt(run: () => Promise<Settled>): Promise<Settled> {
    try {
      return await run();
    } catch (error) {
      return { written: false, message: this.failed(error) };
    }
  }
}
