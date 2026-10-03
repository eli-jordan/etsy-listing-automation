import { act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

/** Fake timers for a page test that still awaits `findBy*`/`waitFor`.
 *
 * The clock keeps ticking with real time (`shouldAdvanceTime`) so Testing
 * Library's polling resolves, but a deadline the test cares about is crossed
 * only by {@link advance}, never by waiting it out. The returned `user` drives
 * the same clock. The caller restores real timers in `afterEach`. */
export function controlledClock() {
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
