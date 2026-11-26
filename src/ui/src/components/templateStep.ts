/**
 * The catalog's order, not the rail's grouping: the rail regroups a template the moment
 * it is approved, and a step order that reshuffled would skip or repeat templates.
 */

export function stepPosition(names: readonly string[], current: string | null): string | null {
  const index = current === null ? -1 : names.indexOf(current);
  return index < 0 ? null : `${index + 1} of ${names.length}`;
}
