import { act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { onTestFinished, vi } from "vitest";

/** Fake timers for a page test that still awaits `findBy*`/`waitFor`.
 *
 * The clock keeps ticking with real time (`shouldAdvanceTime`) so Testing
 * Library's polling resolves, but a deadline the test cares about is crossed
 * only by {@link advance}, never by waiting it out. The returned `user` drives
 * the same clock.
 *
 * Restores real timers when the test finishes, and the `navigator.clipboard`
 * user-event replaces with a getter-only stub: without a global `afterEach`
 * (Vitest's globals are off) user-event cannot detach it, and the next test
 * in the file could no longer install its own clipboard. */
export function controlledClock() {
  const clipboard = Object.getOwnPropertyDescriptor(window.navigator, "clipboard");
  onTestFinished(() => {
    vi.useRealTimers();
    if (clipboard) Object.defineProperty(window.navigator, "clipboard", clipboard);
    else Reflect.deleteProperty(window.navigator, "clipboard");
  });
  vi.useFakeTimers({ shouldAdvanceTime: true });
  return {
    user: userEvent.setup({ advanceTimers: vi.advanceTimersByTime }),
    advance: async (ms: number) => {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(ms);
      });
    },
  };
}
