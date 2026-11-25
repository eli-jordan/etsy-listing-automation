import { type RefObject, useEffect, useRef } from "react";
import { useIsPhone } from "../../phone/usePhone";
import { useSwipe } from "../../phone/useSwipe";
import { type DrawerBounds, isExpandedHeight, sheetDrag } from "./drawerSheet";

/**
 * The listing drawer as a phone bottom sheet: a finger on the sheet (outside
 * its scrolling body, which `useSwipe` leaves to native scrolling) drags it.
 * Down follows the finger and a swipe down dismisses it; up grows it and a
 * swipe up expands it. Off the phone, and for a mouse anywhere, nothing
 * here runs: the desktop handle keeps its own resize.
 */

const OUT_MS = 180;

function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export function useDrawerSwipe(
  panelRef: RefObject<HTMLElement | null>,
  {
    open,
    bounds,
    onHeight,
    onDragging,
    onExpanded,
    onDismiss,
  }: {
    open: boolean;
    bounds: (panel: HTMLElement) => DrawerBounds;
    onHeight: (height: number) => void;
    onDragging: (dragging: boolean) => void;
    onExpanded: (expanded: boolean) => void;
    onDismiss: () => void;
  },
): void {
  const isPhone = useIsPhone();
  const startHeight = useRef<number | null>(null);

  // A sheet swiped out keeps its inline pose until the dialog has closed, so
  // it never flashes back in place on the way out.
  useEffect(() => {
    const panel = panelRef.current;
    if (open || !panel) return;
    panel.style.transition = "";
    panel.style.transform = "";
  }, [open, panelRef]);

  const place = (translate: number) => {
    const panel = panelRef.current;
    if (panel) panel.style.transform = translate > 0 ? `translateY(${translate}px)` : "";
  };

  useSwipe(panelRef, {
    axis: "y",
    enabled: isPhone && open,
    onDrag: (offset) => {
      const panel = panelRef.current;
      if (!panel) return;
      if (offset === 0) {
        // Released short of a swipe: down springs back, up stays grown.
        startHeight.current = null;
        onDragging(false);
        place(0);
        return;
      }
      startHeight.current ??= panel.getBoundingClientRect().height;
      onDragging(true);
      const limits = bounds(panel);
      const pose = sheetDrag(offset, startHeight.current, limits);
      place(pose.translate);
      if (offset < 0) {
        onHeight(pose.height);
        onExpanded(isExpandedHeight(pose.height, limits));
      }
    },
    onSwipe: (direction) => {
      const panel = panelRef.current;
      startHeight.current = null;
      onDragging(false);
      if (!panel) return;
      if (direction === "up") {
        place(0);
        onHeight(bounds(panel).expanded);
        onExpanded(true);
        return;
      }
      if (direction !== "down") {
        place(0);
        return;
      }
      if (prefersReducedMotion()) {
        place(0);
        onDismiss();
        return;
      }
      panel.style.transition = `transform ${OUT_MS}ms ease-in`;
      panel.style.transform = "translateY(100%)";
      window.setTimeout(onDismiss, OUT_MS);
    },
  });
}
