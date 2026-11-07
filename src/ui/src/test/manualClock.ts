import type { Clock } from "../hooks/writeLoop";

/** A clock that moves only when told to. */
export class ManualClock implements Clock {
  private now = 0;
  private timers = new Set<{ at: number; run: () => void }>();

  after = (ms: number, run: () => void) => {
    const timer = { at: this.now + ms, run };
    this.timers.add(timer);
    return () => void this.timers.delete(timer);
  };

  advance(ms: number) {
    this.now += ms;
    for (const timer of [...this.timers]) {
      if (timer.at > this.now) continue;
      this.timers.delete(timer);
      timer.run();
    }
  }
}

/** Lets everything already resolved run. */
export async function turns() {
  for (let i = 0; i < 20; i++) await Promise.resolve();
}
