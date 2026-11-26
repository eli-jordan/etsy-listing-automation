import { type RefObject, useEffect, useEffectEvent } from "react";
import { classifySwipe, lockAxis, type SwipeDirection } from "./swipe";

/**
 * Touch swipes on one element, for the phone layout. Internal to `phone/`:
 * pages swipe through `usePager` or `useSheetDrag`, which own the motion this
 * only classifies. Only a finger counts
 * (`pointerType === "touch"`): a mouse drag on the desktop never swipes, so
 * the hook can stay mounted at every width and still change nothing there.
 *
 * A swipe that starts on something that owns its own drag -- a slider, a
 * strip that scrolls along the same axis, the text field being typed in, or
 * anything marked `data-swipe-ignore` -- is left to that thing. A field that
 * is not focused does not: on a phone a finger moves a caret only once the
 * field has focus, and a form-heavy page (the editor's Details tab) has
 * nowhere else to start a swipe.
 *
 * While the page is pinch-zoomed nothing swipes: a finger then pans the
 * zoomed page, as it does everywhere else on a phone, so a drag that means
 * "look over there" never pages or dismisses.
 */

export interface SwipeOptions {
  /** Which axis the element swipes on. The other axis keeps scrolling. */
  axis: "x" | "y";
  /** Live offset along the axis while the finger is down, once the move has
   * locked onto this axis. */
  onDrag: (offset: number) => void;
  /** The finger lifted: the swipe it made, or null for a release short of
   * one, a cancelled touch, or a move along the other axis. */
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

/** Whether a touch starting at `target` belongs to something between it and
 * the swiping element that handles the same gesture itself. */
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
    // The browser keeps the other axis's scrolling; this element takes ours,
    // unless the page is zoomed in, when the browser pans on both.
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
        // A pinch that ended without a resize event still hands the pan back.
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
