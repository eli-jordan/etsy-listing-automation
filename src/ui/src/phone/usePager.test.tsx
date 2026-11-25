import { act, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { drag, onPhone } from "../test/touch";
import { usePager } from "./usePager";

const TABS = ["variants", "pricing", "images", "details"];

function Pages({
  start,
  onPick = () => undefined,
  refuse = false,
  follow,
  apart = false,
}: {
  start: string;
  onPick?: (tab: string) => void;
  refuse?: boolean;
  follow?: number;
  /** The finger on one element, another one moving. */
  apart?: boolean;
}) {
  const [current, setCurrent] = useState(start);
  const zone = useRef<HTMLDivElement>(null);
  const page = useRef<HTMLDivElement>(null);
  const { previous, next } = usePager(zone, {
    items: TABS,
    current,
    onPick: (tab) => {
      onPick(tab);
      if (!refuse) setCurrent(tab);
    },
    ...(apart ? { moves: page } : {}),
    ...(follow === undefined ? {} : { follow }),
  });
  return (
    <div ref={zone} data-testid="zone">
      <div ref={page} data-testid="page">
        {current}
      </div>
      <button type="button" onClick={() => setCurrent("details")}>
        Details
      </button>
      <span data-testid="steps">{`${previous ?? "-"} ${next ?? "-"}`}</span>
    </div>
  );
}

const zone = () => screen.getByTestId("zone");
const page = () => screen.getByTestId("page");

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("usePager on a phone", () => {
  beforeEach(() => onPhone());

  it("names the neighbours, and none past an end", () => {
    render(<Pages start="variants" />);
    expect(screen.getByTestId("steps")).toHaveTextContent("- pricing");
  });

  it("follows the finger one to one while there is a page to go to", () => {
    render(<Pages start="pricing" />);
    drag(zone(), [200, 100], [150, 102], { lift: false });
    expect(zone().style.transform).toBe("translateX(-50px)");
    expect(zone().style.transition).toBe("none");
  });

  it("resists past the first and the last page", () => {
    render(<Pages start="variants" />);
    drag(zone(), [100, 100], [200, 100], { lift: false });
    expect(zone().style.transform).toBe("translateX(35px)");
  });

  it("slides out towards the finger, then picks, then slides the new page in", () => {
    const onPick = vi.fn();
    render(<Pages start="pricing" onPick={onPick} />);
    drag(zone(), [300, 100], [180, 100]);
    expect(zone().style.transform).toBe("translateX(-28%)");
    expect(zone().style.opacity).toBe("0.2");
    expect(onPick).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(110));
    expect(onPick).toHaveBeenCalledWith("images");
    expect(page()).toHaveTextContent("images");
    expect(zone().style.transform).toBe("");
    expect(zone().style.transition).toContain("200ms ease-out");
  });

  it("picks the page before on a swipe right", () => {
    const onPick = vi.fn();
    render(<Pages start="pricing" onPick={onPick} />);
    drag(zone(), [100, 100], [220, 100]);
    expect(zone().style.transform).toBe("translateX(28%)");
    act(() => vi.advanceTimersByTime(110));
    expect(onPick).toHaveBeenCalledWith("variants");
  });

  it("springs back from a release short of a swipe", () => {
    const onPick = vi.fn();
    render(<Pages start="pricing" onPick={onPick} />);
    drag(zone(), [200, 100], [180, 100]);
    act(() => vi.advanceTimersByTime(500));
    expect(onPick).not.toHaveBeenCalled();
    expect(zone().style.transform).toBe("");
  });

  it("goes nowhere past an end", () => {
    const onPick = vi.fn();
    render(<Pages start="details" onPick={onPick} />);
    drag(zone(), [300, 100], [100, 100]);
    act(() => vi.advanceTimersByTime(500));
    expect(onPick).not.toHaveBeenCalled();
    expect(zone().style.transform).toBe("");
  });

  it("leaves a vertical move to the page's scroll", () => {
    render(<Pages start="pricing" />);
    drag(zone(), [200, 300], [205, 100]);
    expect(zone().style.transform).toBe("");
  });

  it("slides in a page picked some other way, from the side it lives on", () => {
    render(<Pages start="pricing" />);
    act(() => screen.getByRole("button", { name: "Details" }).click());
    expect(page()).toHaveTextContent("details");
    expect(zone().style.transition).toContain("200ms ease-out");
  });

  it("puts the page back when the pick is refused", () => {
    render(<Pages start="pricing" refuse />);
    drag(zone(), [300, 100], [180, 100]);
    act(() => vi.advanceTimersByTime(110 + 200));
    expect(page()).toHaveTextContent("pricing");
    expect(zone().style.transform).toBe("");
  });

  it("moves another element at a share of the finger when asked", () => {
    render(<Pages start="pricing" apart follow={0.5} />);
    drag(zone(), [200, 100], [140, 100], { lift: false });
    expect(page().style.transform).toBe("translateX(-30px)");
    expect(zone().style.transform).toBe("");
  });
});

describe("usePager with reduced motion", () => {
  beforeEach(() => onPhone({ reducedMotion: true }));

  it("picks at once and moves nothing", () => {
    const onPick = vi.fn();
    render(<Pages start="pricing" onPick={onPick} />);
    drag(zone(), [300, 100], [180, 100]);
    expect(onPick).toHaveBeenCalledWith("images");
    expect(zone().style.transform).toBe("");
    expect(zone().style.transition).toBe("");
  });
});

describe("usePager off the phone", () => {
  beforeEach(() => onPhone({ phone: false }));

  it("neither listens nor moves", () => {
    const onPick = vi.fn();
    render(<Pages start="pricing" onPick={onPick} />);
    drag(zone(), [300, 100], [100, 100]);
    act(() => screen.getByRole("button", { name: "Details" }).click());
    act(() => vi.advanceTimersByTime(500));
    expect(onPick).not.toHaveBeenCalled();
    expect(zone().getAttribute("style")).toBeNull();
  });
});
