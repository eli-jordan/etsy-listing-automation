/** The one design a real-render preview can overlay -- `null` for a
 * multi-artwork listing (`on-light`/`on-dark`), the same case
 * `DesignSelect.tsx` treats as read-only, since there is no single "the
 * design" to composite. Shared by `VariantsTab` and `ImagesTab`, the two
 * tabs whose preview panes overlay a listing's design onto a template. */
export function singleDesignName(design: Record<string, string>): string | null {
  const values = Object.values(design);
  if (values.length !== 1) return null;
  const file = (values[0] as string).split("/").pop() ?? "";
  return file.replace(/\.png$/i, "") || null;
}
