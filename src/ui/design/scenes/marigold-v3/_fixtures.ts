import bay from "../../assets/template-cards/fence-bay.jpg";
import berry from "../../assets/template-cards/fence-berry.jpg";
import ivory from "../../assets/template-cards/folded-ivory.jpg";
import yam from "../../assets/template-cards/folded-yam.jpg";
import ivoryInline from "../../assets/template-cards/folded-ivory.jpg?inline";
import yamInline from "../../assets/template-cards/folded-yam.jpg?inline";
import artwork from "../../assets/batch-create/night-hike-club.svg";
import type { BoundingBox } from "../../../src/types";

export const assets = { bay, berry, ivory, yam, artwork };
export const pairImage =
  "data:image/svg+xml," +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="480" viewBox="0 0 960 480"><image href="${ivoryInline}" width="480" height="480"/><image href="${yamInline}" x="480" width="480" height="480"/></svg>`,
  );
export const pairBoxes: BoundingBox[] = [
  [
    { x: 132, y: 188 },
    { x: 335, y: 188 },
    { x: 335, y: 382 },
    { x: 132, y: 382 },
  ],
  [
    { x: 588, y: 188 },
    { x: 791, y: 188 },
    { x: 791, y: 382 },
    { x: 588, y: 382 },
  ],
];
export const initialBox: BoundingBox = [
  { x: 177, y: 142 },
  { x: 305, y: 142 },
  { x: 305, y: 304 },
  { x: 177, y: 304 },
];
export const templates = [
  {
    name: "cc1717-hanging-on-fence",
    label: "Hanging on fence",
    kind: "Colour Matrix",
    image: bay,
    status: "Needs preparation",
    goto: "marigold/edit",
  },
  {
    name: "cc1717-folded",
    label: "Folded shirt",
    kind: "Colour Matrix",
    image: ivory,
    status: "Queued · next",
    goto: "marigold/preparing",
  },
  {
    name: "cc1717-colour-pair",
    label: "Two-shirt scene",
    kind: "Multiple",
    image: yam,
    status: "2 placements",
    goto: "marigold/multiple",
  },
  {
    name: "cc1717-flatlay",
    label: "Flat lay",
    kind: "Single",
    image: ivory,
    status: "Existing renderer",
    goto: "marigold/edit",
  },
];
