import { describe, expect, it } from "vitest";
import {
  isLinked,
  keepOne,
  linking,
  listNames,
  pickFor,
  representative,
  resolve,
  slotFile,
  slotUsers,
  unlinked,
} from "./artwork";

const A = "designs/take-a-hike-dark-ink.png";
const B = "designs/take-a-hike-light-ink.png";
const MOSS = "designs/take-a-hike-moss-special.png";

const TONES = { black: "dark", ivory: "light", moss: "dark", natural: "light" } as const;

/** Interactions Part 2 §3: every Link / Unlink / pick transition, `design`
 * before → after. Colour keys ride along untouched. */
describe("the §3 transitions", () => {
  it("unlinks one design into both slots", () => {
    expect(unlinked({ default: A })).toEqual({ "on-light": A, "on-dark": A });
  });

  it("unlinks an empty draft into two null slots", () => {
    expect(unlinked({})).toEqual({ "on-light": null, "on-dark": null });
  });

  it("keeps colour keys when unlinking", () => {
    expect(unlinked({ default: A, moss: MOSS })).toEqual({
      "on-light": A,
      "on-dark": A,
      moss: MOSS,
    });
  });

  it("picking for dark while linked splits the pair, light keeping the old file", () => {
    expect(pickFor({ default: A }, { kind: "slot", tone: "dark" }, B)).toEqual({
      "on-light": A,
      "on-dark": B,
    });
  });

  it("picking for dark on an empty linked draft leaves light empty", () => {
    expect(pickFor({}, { kind: "slot", tone: "dark" }, B)).toEqual({
      "on-light": null,
      "on-dark": B,
    });
  });

  it("picking for one slot sets only that slot", () => {
    expect(pickFor({ "on-light": null, "on-dark": B }, { kind: "slot", tone: "light" }, A)).toEqual(
      { "on-light": A, "on-dark": B },
    );
  });

  it("picking for all shirts sets default", () => {
    expect(pickFor({ default: A, moss: MOSS }, { kind: "one" }, B)).toEqual({
      default: B,
      moss: MOSS,
    });
  });

  it("links one distinct file straight away", () => {
    expect(linking({ "on-light": A, "on-dark": A })).toEqual({
      kind: "linked",
      design: { default: A },
    });
    expect(linking({ "on-light": null, "on-dark": B, moss: MOSS })).toEqual({
      kind: "linked",
      design: { default: B, moss: MOSS },
    });
  });

  it("links two empty slots to no design", () => {
    expect(linking({ "on-light": null, "on-dark": null })).toEqual({ kind: "linked", design: {} });
  });

  it("asks which to keep when the slots hold two files", () => {
    expect(linking({ "on-light": A, "on-dark": B })).toEqual({ kind: "choose", light: A, dark: B });
  });

  it("keeps the chosen file as default, with the colour keys", () => {
    expect(keepOne({ "on-light": A, "on-dark": B, moss: MOSS }, B)).toEqual({
      default: B,
      moss: MOSS,
    });
  });
});

describe("reading the map", () => {
  it("is linked unless a tone key is present, null included", () => {
    expect(isLinked({})).toBe(true);
    expect(isLinked({ default: A })).toBe(true);
    expect(isLinked({ "on-light": null, "on-dark": null })).toBe(false);
  });

  it("names the file a slot card shows", () => {
    expect(slotFile({ default: A }, { kind: "one" })).toBe(A);
    expect(slotFile({ default: A }, { kind: "slot", tone: "dark" })).toBe(A);
    expect(slotFile({ "on-light": null, "on-dark": B }, { kind: "slot", tone: "light" })).toBe(
      null,
    );
  });

  it("resolves a colour the way config/artwork.py does", () => {
    const pair = { "on-light": A, "on-dark": null, moss: MOSS };
    expect(resolve(pair, "moss", TONES)).toEqual({ kind: "resolved", ref: MOSS, source: "colour" });
    expect(resolve(pair, "ivory", TONES)).toEqual({
      kind: "resolved",
      ref: A,
      source: "on-light",
    });
    expect(resolve(pair, "black", TONES)).toEqual({ kind: "slot-empty", tone: "dark" });
    expect(resolve(pair, "heather", TONES)).toEqual({ kind: "unclassified" });
    expect(resolve({ default: A }, "heather", TONES)).toEqual({
      kind: "resolved",
      ref: A,
      source: "default",
    });
    expect(resolve({}, "black", TONES)).toEqual({ kind: "no-design" });
  });

  it("counts only enabled automatic colours as slot users", () => {
    expect(slotUsers({ "on-dark": B, moss: MOSS }, ["black", "moss", "ivory"], TONES)).toEqual({
      light: ["ivory"],
      dark: ["black"],
    });
  });

  it("represents the listing by default, then on-light, then on-dark", () => {
    expect(representative({ default: A })).toBe(A);
    expect(representative({ "on-light": null, "on-dark": B })).toBe(B);
    expect(representative({ "on-light": A, "on-dark": B })).toBe(A);
    expect(representative({ moss: MOSS })).toBe(null);
  });

  it("lists names the way the banner does", () => {
    expect(listNames([])).toBe("");
    expect(listNames(["ivory"])).toBe("Ivory");
    expect(listNames(["black", "moss", "navy"])).toBe("Black, Moss and Navy");
  });
});
