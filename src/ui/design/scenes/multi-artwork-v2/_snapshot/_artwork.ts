import type { Issue } from "../../../../src/types";

/** One file in the workspace design library. */
export interface Design {
  name: string;
  file: string;
  url: string;
}

export type Tone = "light" | "dark";

/** A colour the garment profile offers. `tone` is `null` when the profile has
 * not classified it -- shared garment data, never fixed from the listing. */
export interface Colour {
  name: string;
  swatch: string;
  tone: Tone | null;
  enabled: boolean;
  /** A direct `design[colour]` exception. */
  own: Design | null;
}

/** The reserved base keys of `design`, as the editor holds them. */
export type Base =
  | { mode: "one"; design: Design | null }
  | { mode: "light-dark"; light: Design | null; dark: Design | null };

/** Where a colour's file came from, which is what its row and the preview
 * card explain. */
export type Resolution =
  | { kind: "own"; design: Design }
  | { kind: "one"; design: Design | null }
  | { kind: "slot"; tone: Tone; design: Design | null }
  | { kind: "unclassified" };

export function resolve(colour: Colour, base: Base): Resolution {
  if (colour.own !== null) return { kind: "own", design: colour.own };
  if (base.mode === "one") return { kind: "one", design: base.design };
  if (colour.tone === null) return { kind: "unclassified" };
  return { kind: "slot", tone: colour.tone, design: base[colour.tone] };
}

export function resolvedDesign(r: Resolution): Design | null {
  return r.kind === "unclassified" ? null : r.design;
}

export const toneLabel = (tone: Tone) => (tone === "light" ? "light shirts" : "dark shirts");

export function listNames(names: string[]): string {
  const cap = names.map((n) => n[0].toUpperCase() + n.slice(1));
  if (cap.length <= 1) return cap.join("");
  return `${cap.slice(0, -1).join(", ")} and ${cap[cap.length - 1]}`;
}

/** Automatic enabled colours of one tone -- the colours that need that base
 * slot once direct exceptions are taken out. */
export function slotUsers(colours: Colour[], tone: Tone): Colour[] {
  return colours.filter((c) => c.enabled && c.own === null && c.tone === tone);
}

/** The server's validation, re-stated for the mockup: incomplete states block
 * deploying, the one-slot case only warns. */
export function artworkIssues(base: Base, colours: Colour[], profile: string): Issue[] {
  const issues: Issue[] = [];
  const enabled = colours.filter((c) => c.enabled);

  const noBase = base.mode === "one" ? base.design === null : base.light === null && base.dark === null;
  if (noBase) {
    issues.push({
      message: "No design is chosen for this listing yet",
      severity: "block",
      tab: "variants",
      where: "Artwork",
    });
  }

  const unclassified = enabled.filter((c) => c.tone === null);
  if (unclassified.length > 0) {
    issues.push({
      message: `${listNames(unclassified.map((c) => c.name))} ${unclassified.length === 1 ? "isn't" : "aren't"} marked light or dark in the ${profile} garment profile`,
      severity: "block",
      tab: "variants",
      where: `Fix it in garment-profiles/${profile}.yaml`,
    });
  }

  if (base.mode === "light-dark" && !noBase) {
    const used: Tone[] = [];
    for (const tone of ["light", "dark"] as const) {
      const users = slotUsers(colours, tone);
      if (users.length === 0) continue;
      used.push(tone);
      if (base[tone] === null) {
        issues.push({
          message: `${listNames(users.map((c) => c.name))} ${users.length === 1 ? `is a ${tone} shirt` : `are ${tone} shirts`}, but no design for ${toneLabel(tone)} is chosen`,
          severity: "block",
          tab: "variants",
          where: `Artwork · For ${toneLabel(tone)}`,
        });
      }
    }
    if (used.length === 1) {
      const other: Tone = used[0] === "light" ? "dark" : "light";
      issues.push({
        message: `Only the design for ${toneLabel(used[0])} is in use — no ${other} shirt you sell needs the design for ${toneLabel(other)}`,
        severity: "warn",
        tab: "variants",
        where: "Artwork · One design for all shirts may be all this listing needs",
      });
    }
  }

  return issues;
}

/** Cloth shown behind a thumbnail: artwork is judged on the shirt it is for. */
export const TILE = { light: "#efe6d2", dark: "#262626", neutral: "var(--color-neutral-200)" };

export const cap = (s: string) => s[0].toUpperCase() + s.slice(1);
