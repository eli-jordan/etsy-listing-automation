import { afterTiles, beforeTiles } from "./_fixtures";

const order = ["black", "white", "yam", "moss", "orchid", "berry", "ivory"];

export const beforeRefs = beforeTiles.map((src, index) => ({ ref: order[index] ?? "", src }));
export const afterRefs = ["ivory", "white", "black", "yam", "moss", "orchid", "berry"];

export function tileFor(ref: string): string | null {
  const index = afterRefs.indexOf(ref);
  return afterTiles[index]?.src ?? null;
}
