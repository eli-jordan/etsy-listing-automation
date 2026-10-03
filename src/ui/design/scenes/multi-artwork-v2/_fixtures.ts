import type { ArtworkEditorProps } from "./_snapshot/_ArtworkEditorScreen";
import type { Colour, Design } from "./_snapshot/_artwork";
import campCoffee from "../../assets/multi-artwork/camp-coffee.svg";
import hike from "../../assets/multi-artwork/take-a-hike.svg";
import hikeDarkInk from "../../assets/multi-artwork/take-a-hike-dark-ink.svg";
import hikeLightInk from "../../assets/multi-artwork/take-a-hike-light-ink.svg";
import hikeMoss from "../../assets/multi-artwork/take-a-hike-moss-special.svg";
import trailMix from "../../assets/multi-artwork/trail-mix.svg";

const design = (name: string, url: string): Design => ({ name, file: `designs/${name}.png`, url });

export const designs = {
  hike: design("take-a-hike", hike),
  darkInk: design("take-a-hike-dark-ink", hikeDarkInk),
  lightInk: design("take-a-hike-light-ink", hikeLightInk),
  moss: design("take-a-hike-moss-special", hikeMoss),
  campCoffee: design("camp-coffee", campCoffee),
  trailMix: design("trail-mix", trailMix),
};

export const library: Design[] = [
  designs.hike,
  designs.darkInk,
  designs.lightInk,
  designs.moss,
  designs.campCoffee,
  designs.trailMix,
];

const colour = (name: string, swatch: string, tone: Colour["tone"], enabled = true): Colour => ({
  name,
  swatch,
  tone,
  enabled,
  own: null,
});

/** The bella-canvas-3001 profile: two light colours, three dark. */
export const colours: Colour[] = [
  colour("black", "#262626", "dark"),
  colour("ivory", "#efe6d2", "light"),
  colour("moss", "#5d6746", "dark"),
  colour("natural", "#e2d3b4", "light"),
  colour("navy", "#28334d", "dark"),
];

export const withOwn = (cs: Colour[], name: string, d: Design) =>
  cs.map((c) => (c.name === name ? { ...c, own: d } : c));

export const common: Pick<ArtworkEditorProps, "listing" | "profile" | "library"> = {
  listing: "Take a hike",
  profile: "bella-canvas-3001",
  library,
};

export const lightDark = { mode: "light-dark", light: designs.darkInk, dark: designs.lightInk } as const;
