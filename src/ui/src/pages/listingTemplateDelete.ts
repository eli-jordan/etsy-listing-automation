export const TEMPLATE_DELETE_DETAILS =
  "The listing template's folder and its own files are removed. Batches and listings made from it are unaffected: they keep their own copies.";

export function templateDeleteTitle(name: string): string {
  return `Delete ${name}?`;
}
