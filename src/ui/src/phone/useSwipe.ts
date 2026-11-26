import { type RefObject, useEffect, useEffectEvent } from "react";
import { classifySwipe, lockAxis, type SwipeDirection } from "./swipe";

/** Classifies touch swipes for `usePager`, `useSheetDrag` and `useCarousel` (src/ui/AGENTS.md). */

export interface SwipeOptions {
  axis: "x" | "y";
  onDrag: (offset: number) => void;
  onEnd: (direction: SwipeDirection | null) => void;
  enabled: boolean;
}

const OWNS_DRAG = "input[type='range'], [role='slider'], [role='separator'], [data-swipe-ignore]";
const TYPED_IN = "input, textarea, [contenteditable=''], [contenteditable='true']";

function isFocusedField(target: Element): boolean {
  const field = target.closest(TYPED_IN);
  return field !== null && field === document.activeElement;
}

export function pinchZoomed(): boolean {
  const viewport = window.visualViewport;
  return viewport != null && viewport.scale > 1.01;
}

function scrollsAlong(element: Element, axis: "x" | "y"): boolean {
  const style = window.getComputedStyle(element);
  const overflow = axis === "x" ? style.overflowX : style.overflowY;
  if (overflow !== "auto" && overflow !== "scroll") return false;
  return axis === "x"
    ? element.scrollWidth > element.clientWidth + 1
    : element.scrollHeight > element.clientHeight + 1;
}

export function ownedElsewhere(
  target: EventTarget | null,
  root: Element,
  axis: "x" | "y",
): boolean {
  if (!(target instanceof Element)) return false;
  if (target.closest(OWNS_DRAG) || isFocusedField(target)) return true;
  for (let node: Element | null = target; node && node !== root; node = node.parentElement) {
    if (scrollsAlong(node, axis)) return true;
  }
  return false;
}

interface Track {
  id: number;
  x: number;
  y: number;
  at: number;
  axis: "x" | "y" | null;
  lockedToOtherAxis: boolean;
}

export function useSwipe(ref: RefObject<HTMLElement | null>, options: SwipeOptions): void {
  const ended = useEffectEvent((direction: SwipeDirection | null) => options.onEnd(direction));
  const dragged = useEffectEvent((offset: number) => options.onDrag(offset));
  const { axis, enabled } = options;

  useEffect(() => {
    const element = ref.current;
    if (!element || !enabled) return;
    let track: Track | null = null;
    const previousTouchAction = element.style.touchAction;
    const ours = axis === "x" ? "pan-y pinch-zoom" : "pan-x pinch-zoom";
    const claim = () => {
      element.style.touchAction = pinchZoomed() ? previousTouchAction : ours;
    };
    claim();
    const viewport = window.visualViewport;
    viewport?.addEventListener("resize", claim);

    const end = (event: PointerEvent, cancelled: boolean) => {
      if (!track || event.pointerId !== track.id) return;
      const { x, y, at, axis: locked, lockedToOtherAxis } = track;
      track = null;
      if (lockedToOtherAxis) return;
      ended(
        cancelled
          ? null
          : classifySwipe(event.clientX - x, event.clientY - y, event.timeStamp - at, locked),
      );
    };
    const onDown = (event: PointerEvent) => {
      if (event.pointerType !== "touch" || !event.isPrimary) return;
      if (pinchZoomed()) {
        // A pinch can end without a visualViewport resize event.
        claim();
        return;
      }
      if (ownedElsewhere(event.target, element, axis)) return;
      track = {
        id: event.pointerId,
        x: event.clientX,
        y: event.clientY,
        at: event.timeStamp,
        axis: null,
        lockedToOtherAxis: false,
      };
    };
    const onMove = (event: PointerEvent) => {
      if (!track || event.pointerId !== track.id || track.lockedToOtherAxis) return;
      const dx = event.clientX - track.x;
      const dy = event.clientY - track.y;
      if (track.axis === null) {
        const locked = lockAxis(dx, dy);
        if (locked === null) return;
        track.axis = locked;
        track.lockedToOtherAxis = locked !== axis;
        if (track.lockedToOtherAxis) return;
      }
      dragged(axis === "x" ? dx : dy);
    };
    const onUp = (event: PointerEvent) => end(event, false);
    const onCancel = (event: PointerEvent) => end(event, true);

    element.addEventListener("pointerdown", onDown);
    element.addEventListener("pointermove", onMove);
    element.addEventListener("pointerup", onUp);
    element.addEventListener("pointercancel", onCancel);
    return () => {
      viewport?.removeEventListener("resize", claim);
      element.style.touchAction = previousTouchAction;
      element.removeEventListener("pointerdown", onDown);
      element.removeEventListener("pointermove", onMove);
      element.removeEventListener("pointerup", onUp);
      element.removeEventListener("pointercancel", onCancel);
    };
  }, [ref, enabled, axis]);
}
