export interface DrawerBounds {
  minimum: number;
  collapsed: number;
  expanded: number;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}

export function grownHeight(by: number, startHeight: number, bounds: DrawerBounds): number {
  return clamp(startHeight + by, bounds.minimum, bounds.expanded);
}

export function fittedHeight(height: number, bounds: DrawerBounds): number {
  return clamp(height, bounds.minimum, bounds.expanded);
}

export function isExpandedHeight(height: number, bounds: DrawerBounds): boolean {
  return height > (bounds.collapsed + bounds.expanded) / 2;
}
