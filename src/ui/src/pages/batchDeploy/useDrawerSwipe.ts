import { type RefObject, useRef } from "react";
import { useSheetDrag } from "../../phone/useSheetDrag";
import { type DrawerBounds, grownHeight, isExpandedHeight } from "./drawerSheet";

/**
 * The listing drawer as a phone bottom sheet: a finger on the sheet (outside
 * its scrolling body, which keeps native scrolling) drags it. Down is the
 * phone's one sheet drag (`useSheetDrag`): it follows the finger, and a
 * swipe down dismisses. Up grows it and a swipe up expands it. Off the
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
        // Released short of a swipe up, the sheet stays as tall as it grew.
        if (!swiped || !panel) return;
        onHeight(bounds(panel).expanded);
        onExpanded(true);
      },
    },
  });
}
