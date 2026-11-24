import { type RefObject, useEffect, useEffectEvent } from "react";
import { classifySwipe, lockAxis, type SwipeDirection } from "./swipe";

/**
 * Touch swipes on one element, for the phone layout. Only a finger counts
 * (`pointerType === "touch"`): a mouse drag on the desktop never swipes, so
 * the hook can stay mounted at every width and still change nothing there.
 *
 * A swipe that starts on something that owns its own drag -- a text field, a
 * slider, a horizontally scrolling strip, or anything marked
 * `data-swipe-ignore` -- is left to that thing.
 */

export interface SwipeOptions {
  /** Which axis the element swipes on. The other axis keeps scrolling. */
  axis: "x" | "y";
  onSwipe: (direction: SwipeDirection) => void;
  /** Live offset along the axis while the finger is down, for a drag that
   * follows the finger. A release that is not a swipe reports 0 (spring
   * back); a swipe reports nothing more, and `onSwipe` places the element. */
  onDrag?: (offset: number) => void;
  enabled?: boolean;
}

const OWNS_DRAG =
  "input, textarea, select, [contenteditable=''], [contenteditable='true'], [data-swipe-ignore], [role='slider']";

function scrollsAlong(element: Element, axis: "x" | "y"): boolean {
  const style = window.getComputedStyle(element);
  const overflow = axis === "x" ? style.overflowX : style.overflowY;
  if (overflow !== "auto" && overflow !== "scroll") return false;
  return axis === "x"
    ? element.scrollWidth > element.clientWidth + 1
    : element.scrollHeight > element.clientHeight + 1;
}

/** Whether a touch starting at `target` belongs to something between it and
 * the swiping element that handles the same gesture itself. */
export function ownedElsewhere(
  target: EventTarget | null,
  root: Element,
  axis: "x" | "y",
): boolean {
  if (!(target instanceof Element)) return false;
  if (target.closest(OWNS_DRAG)) return true;
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
  /** Locked to the other axis: this touch is a scroll, not ours. */
  ignored: boolean;
}

export function useSwipe(ref: RefObject<HTMLElement | null>, options: SwipeOptions): void {
  const swiped = useEffectEvent((direction: SwipeDirection) => options.onSwipe(direction));
  const dragged = useEffectEvent((offset: number) => options.onDrag?.(offset));
  const enabled = options.enabled ?? true;
  const { axis } = options;

  useEffect(() => {
    const element = ref.current;
    if (!element || !enabled) return;
    let track: Track | null = null;
    // The browser keeps the other axis's scrolling; this element takes ours.
    const previousTouchAction = element.style.touchAction;
    element.style.touchAction = axis === "x" ? "pan-y pinch-zoom" : "pan-x pinch-zoom";

    const end = (event: PointerEvent, cancelled: boolean) => {
      if (!track || event.pointerId !== track.id) return;
      const { x, y, at, axis: locked, ignored } = track;
      track = null;
      const direction =
        cancelled || ignored
          ? null
          : classifySwipe(event.clientX - x, event.clientY - y, event.timeStamp - at, locked);
      // A swipe hands the element to `onSwipe`, which decides where it ends
      // up; anything else springs back.
      if (direction) swiped(direction);
      else dragged(0);
    };
    const onDown = (event: PointerEvent) => {
      if (event.pointerType !== "touch" || !event.isPrimary) return;
      if (ownedElsewhere(event.target, element, axis)) return;
      track = {
        id: event.pointerId,
        x: event.clientX,
        y: event.clientY,
        at: event.timeStamp,
        axis: null,
        ignored: false,
      };
    };
    const onMove = (event: PointerEvent) => {
      if (!track || event.pointerId !== track.id || track.ignored) return;
      const dx = event.clientX - track.x;
      const dy = event.clientY - track.y;
      if (track.axis === null) {
        const locked = lockAxis(dx, dy);
        if (locked === null) return;
        track.axis = locked;
        track.ignored = locked !== axis;
        if (track.ignored) return;
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
      element.style.touchAction = previousTouchAction;
      element.removeEventListener("pointerdown", onDown);
      element.removeEventListener("pointermove", onMove);
      element.removeEventListener("pointerup", onUp);
      element.removeEventListener("pointercancel", onCancel);
    };
  }, [ref, enabled, axis]);
}
