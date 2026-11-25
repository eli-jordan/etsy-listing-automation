/**
 * The listing drawer's finger arithmetic on a phone, free of the DOM so it
 * is tested on numbers. The drawer is a bottom sheet there: pulled down it
 * follows the finger out, pulled up it grows towards its expanded height.
 */

export interface DrawerBounds {
  minimum: number;
  collapsed: number;
  expanded: number;
}

export interface SheetPose {
  /** How far the sheet sits below its resting place, in px. */
  translate: number;
  height: number;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}

/** Where a drag of `offset` px (down is positive) from `startHeight` puts
 * the sheet. Down moves the whole sheet, so it can leave; up grows it, never
 * past its expanded height, the way the desktop handle resizes it. */
export function sheetDrag(offset: number, startHeight: number, bounds: DrawerBounds): SheetPose {
  if (offset >= 0) return { translate: offset, height: startHeight };
  return {
    translate: 0,
    height: clamp(startHeight - offset, bounds.minimum, bounds.expanded),
  };
}

/** Whether a height counts as the expanded drawer, by the same midpoint the
 * desktop handle uses. */
export function isExpandedHeight(height: number, bounds: DrawerBounds): boolean {
  return height > (bounds.collapsed + bounds.expanded) / 2;
}
