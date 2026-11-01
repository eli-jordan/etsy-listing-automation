import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useNow } from "./useNow";

afterEach(() => vi.useRealTimers());

it("updates every fifteen seconds and releases its timer on unmount", () => {
  vi.useFakeTimers();
  vi.setSystemTime(1000);
  const { result, unmount } = renderHook(() => useNow());
  expect(result.current).toBe(1000);
  act(() => vi.advanceTimersByTime(15_000));
  expect(result.current).toBe(16_000);
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});
