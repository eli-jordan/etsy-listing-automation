/** A drifted field's page anchor, shared by its row and the warning's links. */
export function driftRowId(key: string): string {
  return `drift-${key.replace(":", "-")}`;
}

/** Scrolls a drifted field into view, once any opening has rendered. */
export function scrollToDriftRow(key: string): void {
  requestAnimationFrame(() => {
    document
      .getElementById(driftRowId(key))
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  });
}
