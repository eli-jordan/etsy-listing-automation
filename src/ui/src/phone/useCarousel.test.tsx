import { act, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Lightbox, type LightboxItem } from "../components/Lightbox";
import { drag, onPhone } from "../test/touch";

const ITEMS: LightboxItem[] = [
  { id: "black", label: "black", url: "blob:black" },
  { id: "ivory", label: "ivory", url: "blob:ivory" },
  { id: "moss", label: "moss", url: "blob:moss" },
];

function Viewer({ start, onIndexChange }: { start: number; onIndexChange: (i: number) => void }) {
  const [index, setIndex] = useState(start);
  return (
    <Lightbox
      items={ITEMS}
      index={index}
      actualSize={false}
      onActualSizeChange={() => undefined}
      onIndexChange={(next) => {
        onIndexChange(next);
        setIndex(next);
      }}
      onClose={() => undefined}
    />
  );
}

const stage = () => document.querySelector(".lightbox__stage") as HTMLElement;
const track = () => document.querySelector(".lightbox__track") as HTMLElement;
const slide = (place: string) =>
  document.querySelector(`.lightbox__slide--${place} img`)?.getAttribute("alt") ?? null;

beforeEach(() => {
  vi.useFakeTimers();
  onPhone();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("The Lightbox's carousel on a phone", () => {
  it("lays the neighbours out either side, out of reach of a screen reader", () => {
    render(<Viewer start={1} onIndexChange={() => undefined} />);
    expect([slide("previous"), slide("current"), slide("next")]).toEqual([
      "black",
      "ivory",
      "moss",
    ]);
    expect(screen.getByAltText("ivory")).toBeVisible();
    expect(document.querySelector(".lightbox__slide--next")).toHaveAttribute("aria-hidden", "true");
  });

  it("drags the whole strip with the finger, so a part-swipe shows both", () => {
    render(<Viewer start={1} onIndexChange={() => undefined} />);
    drag(stage(), [200, 100], [150, 102], { lift: false });
    expect(track().style.transform).toBe("translateX(-50px)");
  });

  it("carries a swipe on until the neighbour is centred, then steps to it", () => {
    const onIndexChange = vi.fn();
    render(<Viewer start={1} onIndexChange={onIndexChange} />);
    const moss = screen.getByAltText("moss");
    drag(stage(), [300, 100], [180, 100]);
    expect(track().style.transform).toBe("translateX(calc(-100% - var(--lightbox-gap)))");
    expect(onIndexChange).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(220));
    expect(onIndexChange).toHaveBeenCalledWith(2);
    // The strip is back at rest with the neighbour now in the middle, and the
    // picture that slid in is the same element, already loaded.
    expect(track().style.transform).toBe("");
    expect(track().style.transition).toBe("");
    expect(slide("current")).toBe("moss");
    expect(screen.getByAltText("moss")).toBe(moss);
    expect(slide("previous")).toBe("ivory");
    expect(slide("next")).toBeNull();
  });

  it("steps back on a swipe right", () => {
    const onIndexChange = vi.fn();
    render(<Viewer start={1} onIndexChange={onIndexChange} />);
    drag(stage(), [100, 100], [220, 100]);
    expect(track().style.transform).toBe("translateX(calc(100% + var(--lightbox-gap)))");
    act(() => vi.advanceTimersByTime(220));
    expect(onIndexChange).toHaveBeenCalledWith(0);
  });

  it("resists past the last picture and goes nowhere", () => {
    const onIndexChange = vi.fn();
    render(<Viewer start={2} onIndexChange={onIndexChange} />);
    drag(stage(), [300, 100], [200, 100], { lift: false });
    expect(track().style.transform).toBe("translateX(-35px)");
    drag(stage(), [300, 100], [100, 100]);
    act(() => vi.advanceTimersByTime(500));
    expect(onIndexChange).not.toHaveBeenCalled();
    expect(track().style.transform).toBe("");
  });

  it("with reduced motion, steps at once", () => {
    onPhone({ reducedMotion: true });
    const onIndexChange = vi.fn();
    render(<Viewer start={0} onIndexChange={onIndexChange} />);
    drag(stage(), [300, 100], [180, 100]);
    expect(onIndexChange).toHaveBeenCalledWith(1);
    expect(track().style.transform).toBe("");
  });
});
