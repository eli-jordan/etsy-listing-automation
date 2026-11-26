import type { DesignMap } from "../../types";

export type Tone = "light" | "dark";

const DEFAULT = "default";
const TONE_KEY = { light: "on-light", dark: "on-dark" } as const;
const BASE_KEYS: readonly string[] = [DEFAULT, TONE_KEY.light, TONE_KEY.dark];

/** What a base-slot card, a Recent panel or the full picker is choosing a
 * file for. Linked, the left card is `one` (`design.default`); unlinked it is
 * the light slot. The right card is always the dark slot. */
export type SlotTarget = { kind: "one" } | { kind: "slot"; tone: Tone };

export type Resolution =
  | { kind: "resolved"; ref: string; source: "colour" | "default" | "on-light" | "on-dark" }
  | { kind: "slot-empty"; tone: Tone }
  | { kind: "unclassified" }
  | { kind: "no-design" };

export function isLinked(design: DesignMap): boolean {
  return !(TONE_KEY.light in design || TONE_KEY.dark in design);
}

export function resolve(
  design: DesignMap,
  colour: string,
  tones: Readonly<Record<string, Tone>>,
): Resolution {
  const own = design[colour];
  if (own !== undefined && own !== null) {
    return { kind: "resolved", ref: own, source: "colour" };
  }
  if (!isLinked(design)) {
    const tone = tones[colour];
    if (tone === undefined) return { kind: "unclassified" };
    const ref = design[TONE_KEY[tone]] ?? null;
    return ref === null
      ? { kind: "slot-empty", tone }
      : { kind: "resolved", ref, source: TONE_KEY[tone] };
  }
  const ref = design[DEFAULT] ?? null;
  return ref === null ? { kind: "no-design" } : { kind: "resolved", ref, source: "default" };
}

export function slotUsers(
  design: DesignMap,
  enabled: readonly string[],
  tones: Readonly<Record<string, Tone>>,
): Record<Tone, string[]> {
  const users: Record<Tone, string[]> = { light: [], dark: [] };
  for (const colour of enabled) {
    if ((design[colour] ?? null) !== null) continue;
    const tone = tones[colour];
    if (tone !== undefined) users[tone].push(colour);
  }
  return users;
}

export function representative(design: DesignMap): string | null {
  for (const key of BASE_KEYS) {
    const ref = design[key] ?? null;
    if (ref !== null) return ref;
  }
  return null;
}

/** The file a slot card shows. Linked, both cards show `default` -- the dark
 * one only mirrors it. */
export function slotFile(design: DesignMap, target: SlotTarget): string | null {
  if (isLinked(design)) return design[DEFAULT] ?? null;
  return target.kind === "slot" ? (design[TONE_KEY[target.tone]] ?? null) : null;
}

function colourKeys(design: DesignMap): DesignMap {
  return Object.fromEntries(Object.entries(design).filter(([key]) => !BASE_KEYS.includes(key)));
}

export function unlinked(design: DesignMap): DesignMap {
  const file = design[DEFAULT] ?? null;
  return { [TONE_KEY.light]: file, [TONE_KEY.dark]: file, ...colourKeys(design) };
}

export function pickFor(design: DesignMap, target: SlotTarget, ref: string): DesignMap {
  if (target.kind === "one") return { [DEFAULT]: ref, ...colourKeys(design) };
  const base = isLinked(design) ? unlinked(design) : design;
  return { ...base, [TONE_KEY[target.tone]]: ref };
}

export type Linking =
  { kind: "linked"; design: DesignMap } | { kind: "choose"; light: string; dark: string };

export function linking(design: DesignMap): Linking {
  const light = design[TONE_KEY.light] ?? null;
  const dark = design[TONE_KEY.dark] ?? null;
  if (light !== null && dark !== null && light !== dark) return { kind: "choose", light, dark };
  const kept = light ?? dark;
  return { kind: "linked", design: kept === null ? colourKeys(design) : keepOne(design, kept) };
}

export function keepOne(design: DesignMap, ref: string): DesignMap {
  return { [DEFAULT]: ref, ...colourKeys(design) };
}

export function canHaveOwnDesign(design: DesignMap): boolean {
  return BASE_KEYS.some((key) => key in design);
}

export function pickForColour(design: DesignMap, colour: string, ref: string): DesignMap {
  return { ...design, [colour]: ref };
}

export function automatic(design: DesignMap, colour: string): DesignMap {
  if (BASE_KEYS.includes(colour)) return design;
  return Object.fromEntries(Object.entries(design).filter(([key]) => key !== colour));
}

export function wouldPrintAutomatically(
  design: DesignMap,
  colour: string,
  tones: Readonly<Record<string, Tone>>,
): Resolution {
  return resolve(automatic(design, colour), colour, tones);
}

export const toneLabel = (tone: Tone): string =>
  tone === "light" ? "light shirts" : "dark shirts";

export const cap = (name: string): string =>
  name === "" ? name : name.charAt(0).toUpperCase() + name.slice(1);

/** "Black, Moss and Navy" -- the same list the server's messages spell. */
export function listNames(names: readonly string[]): string {
  const capped = names.map(cap);
  if (capped.length <= 1) return capped.join("");
  return `${capped.slice(0, -1).join(", ")} and ${capped[capped.length - 1]}`;
}

export const TILE = {
  light: "#efe6d2",
  dark: "#262626",
  neutral: "var(--color-neutral-200)",
} as const;

/** The cloth a colour's own thumbnails sit on: its sampled garment swatch,
 * else its tone's tile -- the row chip, the card under the stage and the
 * colour's picker all judge a file on the shirt that prints it. */
export function clothFor(
  colour: string,
  swatch: string | undefined,
  design: DesignMap,
  tones: Readonly<Record<string, Tone>>,
): string {
  if (swatch !== undefined) return swatch;
  const tone = tones[colour];
  return tone === undefined || isLinked(design) ? TILE.neutral : TILE[tone];
}
