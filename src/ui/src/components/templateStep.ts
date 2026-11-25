/**
 * Where the open template sits in the order the phone header's arrows and
 * its left/right swipe step through (`usePager`).
 *
 * The catalog's own order, not the rail's grouping: the rail moves a template
 * from "Needs calibration" to "Calibrated" the moment it is approved, and a
 * step order that reshuffled itself under the seller's thumb would skip or
 * repeat templates. No wrap-around either, so the ends read as ends.
 */

/** "3 of 23", or nothing when the open template is not in the list. */
export function stepPosition(names: readonly string[], current: string | null): string | null {
  const index = current === null ? -1 : names.indexOf(current);
  return index < 0 ? null : `${index + 1} of ${names.length}`;
}
