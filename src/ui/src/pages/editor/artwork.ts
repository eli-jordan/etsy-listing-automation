import type { DesignMap } from "../../types";

/**
 * What a listing's `design:` map prints, for the editor's words and pictures
 * (docs/multi-artwork-ui.md; interactions Part 2 §3, §10).
 *
 * `resolve`, `slotUsers` and `representative` mirror `config/artwork.py`
 * (A35). The server stays the authority on what deploys -- the banner renders
 * `detail.issues` and nothing here produces an issue -- but the strip's
 * "Prints on Ivory and Natural" and the card under the stage have to say which
 * file a colour prints before a save has landed, so the rule is restated for
 * display only. The transitions below are the one place the map's shape is
 * edited: every Link, Unlink and pick in the strip goes through them and then
 * through `update(patch)`.
 */

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

/** Light/dark mode is the presence of a tone *key*, `null` included -- that is
 * how an empty pair survives a reload (spec: *A partial light/dark pair*). */
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

/** The enabled *automatic* colours of each tone, in enabled order: a colour
 * with its own design, or with no tone, needs neither base slot. */
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

/** The one file that stands for the listing: first non-null of `default`,
 * `on-light`, `on-dark`. A colour key is never promoted. */
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

/** Everything but the reserved base keys: the colour exceptions, which every
 * mode change keeps (spec: *Base artwork mode*). */
function colourKeys(design: DesignMap): DesignMap {
  return Object.fromEntries(Object.entries(design).filter(([key]) => !BASE_KEYS.includes(key)));
}

/** Unlink: the current file goes into both slots, so the listing still prints
 * what it printed. An empty draft records the mode with two `null`s. */
export function unlinked(design: DesignMap): DesignMap {
  const file = design[DEFAULT] ?? null;
  return { [TONE_KEY.light]: file, [TONE_KEY.dark]: file, ...colourKeys(design) };
}

/** A file picked for a target. A slot picked while linked splits the pair:
 * the other slot keeps the file it had (interactions §3, "Use a different
 * one"). */
export function pickFor(design: DesignMap, target: SlotTarget, ref: string): DesignMap {
  if (target.kind === "one") return { [DEFAULT]: ref, ...colourKeys(design) };
  const base = isLinked(design) ? unlinked(design) : design;
  return { ...base, [TONE_KEY[target.tone]]: ref };
}

/** Link: straight away when there is nothing to choose between, otherwise the
 * two files the seller has to choose from. Nothing is written until then. */
export type Linking =
  { kind: "linked"; design: DesignMap } | { kind: "choose"; light: string; dark: string };

export function linking(design: DesignMap): Linking {
  const light = design[TONE_KEY.light] ?? null;
  const dark = design[TONE_KEY.dark] ?? null;
  if (light !== null && dark !== null && light !== dark) return { kind: "choose", light, dark };
  const kept = light ?? dark;
  return { kind: "linked", design: kept === null ? colourKeys(design) : keepOne(design, kept) };
}

/** The file the seller chose to keep, as the one design for every shirt. */
export function keepOne(design: DesignMap, ref: string): DesignMap {
  return { [DEFAULT]: ref, ...colourKeys(design) };
}

/** Whether a colour can be given its own design: a colour key needs a
 * reserved base key beside it, `null` slots included, or the server refuses
 * the write as malformed (spec: *Saving, blockers and warnings*). An empty
 * draft chooses its base design first. */
export function canHaveOwnDesign(design: DesignMap): boolean {
  return BASE_KEYS.some((key) => key in design);
}

/** A colour's own design: its key in `design`, in either mode, with the base
 * keys untouched (interactions Part 1 §6). */
export function pickForColour(design: DesignMap, colour: string, ref: string): DesignMap {
  return { ...design, [colour]: ref };
}

/** Back to automatic: the colour's key goes, immediately (spec:
 * *Colour-specific artwork*). A base key is never a colour's to remove. */
export function automatic(design: DesignMap, colour: string): DesignMap {
  if (BASE_KEYS.includes(colour)) return design;
  return Object.fromEntries(Object.entries(design).filter(([key]) => key !== colour));
}

/** What the colour would print back on automatic -- said on the card before
 * **Use automatic design** is pressed, so the action needs no confirmation
 * (interactions Part 1 §7). */
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

/** Cloth behind a thumbnail: artwork is judged on the shirt it is for, and
 * light ink on a light tile would be invisible (interactions, *Show artwork
 * on the cloth it's for*). */
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
