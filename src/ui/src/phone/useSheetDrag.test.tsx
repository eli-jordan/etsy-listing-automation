import { act, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { drag, onPhone } from "../test/touch";
import { type SheetGrow, useSheetDrag } from "./useSheetDrag";

function Sheet({
  onDismiss,
  enabled = true,
  fade = false,
  grow,
}: {
  onDismiss: () => void;
  enabled?: boolean;
  fade?: boolean;
  grow?: SheetGrow;
}) {
  const box = useRef<HTMLDivElement>(null);
  const bar = useRef<HTMLDivElement>(null);
  useSheetDrag(bar, { moves: box, onDismiss, enabled, fade, ...(grow ? { grow } : {}) });
  return (
    <div ref={box} data-testid="sheet">
      <div ref={bar} data-testid="grabber" />
    </div>
  );
}

const sheet = () => screen.getByTestId("sheet");
const grabber = () => screen.getByTestId("grabber");

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useSheetDrag on a phone", () => {
  beforeEach(() => onPhone());

  it("follows the finger down", () => {
    render(<Sheet onDismiss={vi.fn()} />);
    drag(grabber(), [100, 100], [100, 160], { lift: false });
    expect(sheet().style.transform).toBe("translateY(60px)");
    expect(sheet().style.transition).toBe("none");
  });

  it("stays put when pulled up", () => {
    render(<Sheet onDismiss={vi.fn()} />);
    drag(grabber(), [100, 300], [100, 200], { lift: false });
    expect(sheet().style.transform).toBe("");
  });

  it("slides out on a swipe down, then dismisses", () => {
    const onDismiss = vi.fn();
    render(<Sheet onDismiss={onDismiss} />);
    drag(grabber(), [100, 100], [100, 300]);
    expect(sheet().style.transform).toBe("translateY(100%)");
    expect(sheet().style.transition).toBe("transform 180ms ease-in");
    expect(onDismiss).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(180));
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it("springs back from a release short of a swipe, then gives the stylesheet its transitions back", () => {
    const onDismiss = vi.fn();
    render(<Sheet onDismiss={onDismiss} />);
    drag(grabber(), [100, 100], [100, 120]);
    expect(sheet().style.transform).toBe("");
    expect(sheet().style.transition).toContain("180ms ease-out");
    act(() => vi.advanceTimersByTime(180));
    expect(sheet().style.transition).toBe("");
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it("fades as it is pulled down when asked", () => {
    render(<Sheet onDismiss={vi.fn()} fade />);
    drag(grabber(), [100, 100], [100, 300], { lift: false });
    expect(sheet().style.opacity).toBe("0.5");
  });

  it("hands an upward drag to grow, and says whether it was a swipe up", () => {
    const grow = { onDrag: vi.fn(), onRelease: vi.fn() };
    render(<Sheet onDismiss={vi.fn()} grow={grow} />);
    drag(grabber(), [100, 300], [100, 200]);
    expect(grow.onDrag).toHaveBeenLastCalledWith(100);
    expect(grow.onRelease).toHaveBeenCalledWith(true);
    expect(sheet().style.transform).toBe("");
  });

  it("stays slid out until the sheet closes, then lets go of it", () => {
    const { rerender } = render(<Sheet onDismiss={vi.fn()} />);
    drag(grabber(), [100, 100], [100, 300]);
    act(() => vi.advanceTimersByTime(180));
    expect(sheet().style.transform).toBe("translateY(100%)");
    rerender(<Sheet onDismiss={vi.fn()} enabled={false} />);
    expect(sheet().style.transform).toBe("");
  });
});

describe("useSheetDrag with reduced motion", () => {
  beforeEach(() => onPhone({ reducedMotion: true }));

  it("dismisses at once on a swipe down", () => {
    const onDismiss = vi.fn();
    render(<Sheet onDismiss={onDismiss} />);
    drag(grabber(), [100, 100], [100, 300]);
    expect(onDismiss).toHaveBeenCalledOnce();
    expect(sheet().style.transform).toBe("");
  });
});

describe("useSheetDrag off the phone", () => {
  beforeEach(() => onPhone({ phone: false }));

  it("neither listens nor moves", () => {
    const onDismiss = vi.fn();
    render(<Sheet onDismiss={onDismiss} />);
    drag(grabber(), [100, 100], [100, 300]);
    act(() => vi.advanceTimersByTime(500));
    expect(onDismiss).not.toHaveBeenCalled();
    expect(sheet().getAttribute("style")).toBeNull();
  });
});
