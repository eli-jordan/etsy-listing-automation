import { type RefObject, useEffect, useRef } from "react";
import { pose, prefersReducedMotion, springBack } from "./motion";
import { useIsPhone } from "./usePhone";
import { useSwipe } from "./useSwipe";

/**
 * Pull down to dismiss, for anything the phone layout shows as a sheet: the
 * grab bar of every bottom sheet (`SheetGrabber`), the deploy drawer, and the
 * Lightbox's picture. Every one goes through here, so they all feel the same:
 *
 * - Pulled down, the moving element follows the finger one to one. Pulled
 *   up, it stays put, unless `grow` hands the upward drag to the caller.
 * - A swipe down slides it the rest of the way out in 180ms, then dismisses;
 *   a release short of one springs back over 180ms.
 * - With `prefers-reduced-motion`, a swipe down dismisses at once.
 *
 * Phone only, and a finger only: off the phone layout nothing listens and
 * nothing moves. A scrolling body inside keeps its own scroll.
 *
 * The element stays slid out until the sheet closes (`enabled` goes false or
 * the hook unmounts), so a dialog's closing animation never shows it
 * flashing back into place first.
 */

export interface SheetGrow {
  /** The finger is `by` px above where it started. */
  onDrag: (by: number) => void;
  /** The finger lifted after any drag; `swiped` when it was a swipe up. */
  onRelease: (swiped: boolean) => void;
}

export interface SheetDragOptions {
  onDismiss: () => void;
  /** Off while the sheet is closed. */
  enabled?: boolean;
  /** The element that moves, when it is not `zone` itself. */
  moves?: RefObject<HTMLElement | null>;
  /** Fade the element as it is pulled down, for something with no box of
   * its own to read as leaving (the Lightbox's picture on its dark ground). */
  fade?: boolean;
  /** Up grows the sheet (the deploy drawer) rather than doing nothing. */
  grow?: SheetGrow;
}

const OUT_MS = 180;

/** How faint a fading element is `down` px from where it started. */
function fadeAt(down: number): string {
  return String(Math.max(0.4, 1 - down / 400));
}

export function useSheetDrag(zone: RefObject<HTMLElement | null>, options: SheetDragOptions): void {
  const { onDismiss, fade = false, grow } = options;
  const isPhone = useIsPhone();
  const enabled = isPhone && (options.enabled ?? true);
  const moves = options.moves ?? zone;
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (!enabled) return;
    const element = moves.current;
    return () => {
      window.clearTimeout(timer.current);
      if (element) pose(element, "", "");
    };
  }, [enabled, moves]);

  const leave = (element: HTMLElement) => {
    const opacity = element.style.opacity;
    pose(element, "translateY(100%)", `transform ${OUT_MS}ms ease-in`, opacity);
    timer.current = window.setTimeout(onDismiss, OUT_MS);
  };

  useSwipe(zone, {
    axis: "y",
    enabled,
    onDrag: (offset) => {
      const element = moves.current;
      if (element === null) return;
      const down = Math.max(offset, 0);
      pose(element, down ? `translateY(${down}px)` : "", "none", fade && down ? fadeAt(down) : "");
      if (offset < 0) grow?.onDrag(-offset);
    },
    onEnd: (direction) => {
      const element = moves.current;
      grow?.onRelease(direction === "up");
      if (element === null) return;
      if (direction !== "down") {
        springBack(element);
      } else if (prefersReducedMotion()) {
        pose(element, "", "");
        onDismiss();
      } else {
        leave(element);
      }
    },
  });
}
