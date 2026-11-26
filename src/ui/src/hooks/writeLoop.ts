export const AUTOSAVE_DEBOUNCE_MS = 800;

export type Settled = { written: true } | { written: false; message: string };

export const WRITTEN: Settled = { written: true };

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
  send: (edit: Edit) => Promise<Settled>;
  merge: (older: Edit, newer: Edit) => Edit;
  failed: (error: unknown) => string;
  due?: () => void;
  clock?: Clock;
}

export class WriteLoop<Edit> {
  private waiting: Edit | null = null;
  private cancelDebounce: (() => void) | null = null;
  private flushedSinceWriteBegan = false;
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

  get held(): Edit | null {
    return this.waiting;
  }

  get armed(): boolean {
    return this.cancelDebounce !== null;
  }

  edit(edit: Edit) {
    this.waiting = this.waiting === null ? edit : this.merge(this.waiting, edit);
    this.disarm();
    this.cancelDebounce = this.clock.after(AUTOSAVE_DEBOUNCE_MS, () => {
      this.cancelDebounce = null;
      this.due();
    });
  }

  /** Starts synchronously when nothing is out: a page being left may get no further turn. */
  flush(): Promise<Settled> {
    this.disarm();
    this.flushedSinceWriteBegan = true;
    if (!this.draining) {
      this.draining = true;
      this.finished = this.drain();
    }
    return this.finished;
  }

  afterWrite(task: () => Promise<void>): Promise<Settled> {
    this.tasks.push(task);
    return this.flush();
  }

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
      if (this.flushedSinceWriteBegan) {
        this.flushedSinceWriteBegan = false;
        if (this.waiting !== null) settled = await this.write(this.waiting);
        continue;
      }
      const task = this.tasks.shift();
      if (task === undefined) break;
      if (settled.written) settled = await this.attempt(() => task().then(() => WRITTEN));
    }
    // Same turn as the check above, or a flush could join a drain that has stopped looking.
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
