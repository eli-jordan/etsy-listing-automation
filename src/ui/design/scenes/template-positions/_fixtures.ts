import ivory from "../../assets/template-cards/folded-ivory.jpg";
import yam from "../../assets/template-cards/folded-yam.jpg";
import crimson from "../../assets/template-cards/folded-crimson.jpg";
import white from "../../assets/template-cards/folded-white.jpg";
import bay from "../../assets/template-cards/fence-bay.jpg";
import ivoryInline from "../../assets/template-cards/folded-ivory.jpg?inline";
import yamInline from "../../assets/template-cards/folded-yam.jpg?inline";
import artwork from "../../assets/batch-create/night-hike-club.svg";
import type { Pose, Rect } from "./_geometry";

export { artwork };
export const photos = { ivory, yam, crimson, white, bay };

/** settings.yaml `template_positions:` defaults (spec, Settings). */
export interface Limits {
  scaleMin: number;
  scaleMax: number;
  /** Fraction of box width/height, either way. */
  offset: number;
  /** Degrees either way. */
  rotation: number;
}
export const limits: Limits = { scaleMin: 0.8, scaleMax: 1.1, offset: 0.1, rotation: 15 };

/** cc1717-folded's calibrated box on its 480px photo. */
export const foldedBox: Rect = { x: 177, y: 142, w: 128, h: 162 };

export const identity: Pose = { scale: 1, dx: 0, dy: 0, rotation: 0 };
/** What the seller settled on for this design: a touch smaller, lifted. */
export const tuned: Pose = { scale: 0.92, dx: 0, dy: -0.06, rotation: 0 };
/** Valid once; the template box moved 14px right in a recalibration. */
export const stale: Pose = { scale: 0.92, dx: -0.11, dy: -0.06, rotation: 0 };

/** Two shirts on one 960x480 photo: cc1717-colour-pair. */
export const pairPhoto =
  "data:image/svg+xml," +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="480" viewBox="0 0 960 480"><image href="${ivoryInline}" width="480" height="480"/><image href="${yamInline}" x="480" width="480" height="480"/></svg>`,
  );
export const pairBoxes: { id: string; colour: string; box: Rect }[] = [
  { id: "left-shirt", colour: "ivory", box: { x: 177, y: 142, w: 128, h: 162 } },
  { id: "right-shirt", colour: "yam", box: { x: 657, y: 142, w: 128, h: 162 } },
];

export interface ReelItem {
  label: string;
  photo: string;
  /** Has a listing position for its template. */
  positioned?: boolean;
  /** Prototype link: the frame that previews this entry. */
  goto?: string;
}

export const reel: ReelItem[] = [
  { label: "cc1717-folded · ivory", photo: ivory, positioned: true, goto: "template-positions/01-selected" },
  { label: "cc1717-colour-pair", photo: yam, positioned: true, goto: "template-positions/03-multiple" },
  { label: "cc1717-folded · yam", photo: yam, positioned: true },
  { label: "cc1717-folded · crimson", photo: crimson, positioned: true },
  { label: "cc1717-hanging-on-fence · bay", photo: bay },
  { label: "cc1717-folded · white", photo: white, positioned: true },
];

export interface LocatorItem {
  name: string;
  kind: string;
  photo: string;
  inCount: number;
  open?: boolean;
  colours?: { name: string; in: boolean }[];
}

export const locator: LocatorItem[] = [
  {
    name: "cc1717-folded",
    kind: "Colour matrix · one photo per colour",
    photo: ivory,
    inCount: 4,
    open: true,
    colours: [
      { name: "ivory", in: true },
      { name: "yam", in: true },
      { name: "crimson", in: true },
      { name: "white", in: true },
      { name: "blue-jean", in: false },
    ],
  },
  { name: "cc1717-hanging-on-fence", kind: "Colour matrix · one photo per colour", photo: bay, inCount: 1 },
  { name: "cc1717-colour-pair", kind: "Multiple · several garments in one photo", photo: yam, inCount: 1 },
];
