import { type RefObject, useEffect, useEffectEvent, useRef } from "react";
import { useIsPhone } from "../../phone/usePhone";
import { useSheetDrag } from "../../phone/useSheetDrag";
import { type DrawerBounds, fittedHeight, grownHeight, isExpandedHeight } from "./drawerSheet";

/**
 * The listing drawer as a phone bottom sheet: a finger on the sheet (outside
 * its scrolling body, which keeps native scrolling) drags it. Down is the
 * phone's one sheet drag (`useSheetDrag`): it follows the finger, and a
 * swipe down dismisses. Up grows it and a swipe up expands it. A height it
 * grew to is fitted to the screen again when the screen changes size (the
 * phone turned on its side), so the sheet never rises past the top. Off the
 * phone, and for a mouse anywhere, nothing here runs: the desktop handle
 * keeps its own resize.
 */
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
  const startHeight = useRef<number | null>(null);
  const isPhone = useIsPhone();

  const refit = useEffectEvent(() => {
    const panel = panelRef.current;
    if (!panel || panel.style.height === "") return;
    const limits = bounds(panel);
    const height = fittedHeight(Number.parseFloat(panel.style.height), limits);
    onHeight(height);
    onExpanded(isExpandedHeight(height, limits));
  });

  useEffect(() => {
    if (!open || !isPhone) return;
    refit();
    window.addEventListener("resize", refit);
    return () => window.removeEventListener("resize", refit);
  }, [open, isPhone]);

  useSheetDrag(panelRef, {
    enabled: open,
    onDismiss,
    grow: {
      onDrag: (by) => {
        const panel = panelRef.current;
        if (!panel) return;
        startHeight.current ??= panel.getBoundingClientRect().height;
        // The height follows the finger, so its own transition stays off.
        onDragging(true);
        const limits = bounds(panel);
        const height = grownHeight(by, startHeight.current, limits);
        onHeight(height);
        onExpanded(isExpandedHeight(height, limits));
      },
      onRelease: (swiped) => {
        const panel = panelRef.current;
        startHeight.current = null;
        onDragging(false);
        if (!swiped || !panel) return;
        onHeight(bounds(panel).expanded);
        onExpanded(true);
      },
    },
  });
}
