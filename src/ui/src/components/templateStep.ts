/** The catalog's order, not the rail's: the rail regroups a template once it is
 * approved, so stepping through it would skip or repeat templates. */

export function stepPosition(names: readonly string[], current: string | null): string | null {
  const index = current === null ? -1 : names.indexOf(current);
  return index < 0 ? null : `${index + 1} of ${names.length}`;
}
