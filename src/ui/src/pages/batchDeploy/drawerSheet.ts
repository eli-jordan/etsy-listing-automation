/**
 * The listing drawer's finger arithmetic on a phone, free of the DOM so it
 * is tested on numbers. The drawer is a bottom sheet there: pulled up it
 * grows towards its expanded height.
 */

export interface DrawerBounds {
  minimum: number;
  collapsed: number;
  expanded: number;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}

/** The height a drag `by` px upwards from `startHeight` grows the sheet to,
 * never past its expanded height, the way the desktop handle resizes it.
 * (Down is the phone's sheet drag, which moves the whole sheet.) */
export function grownHeight(by: number, startHeight: number, bounds: DrawerBounds): number {
  return clamp(startHeight + by, bounds.minimum, bounds.expanded);
}

/** A height the sheet grew to, kept inside new bounds after the screen
 * changed size (a phone turned on its side). */
export function fittedHeight(height: number, bounds: DrawerBounds): number {
  return clamp(height, bounds.minimum, bounds.expanded);
}

/** Whether a height counts as the expanded drawer, by the same midpoint the
 * desktop handle uses. */
export function isExpandedHeight(height: number, bounds: DrawerBounds): boolean {
  return height > (bounds.collapsed + bounds.expanded) / 2;
}
