import { asTag, templates as labelled } from "../template-labels/_fixtures";

export const LISTING = "santa-cookie-crew";
export const COLOURS = ["ivory", "crimson", "moss", "black"];

export interface PickerTemplate {
  name: string;
  src: string;
  tags: string[];
}

export const templates: PickerTemplate[] = labelled.map((t) => ({
  name: t.name,
  src: t.src,
  tags: t.labels.flatMap((l) => asTag(l) ?? []),
}));

export interface Entry {
  template: string;
  colour: string;
}

export const initialMedia: Entry[] = [
  { template: "cc1717-woman-by-christmas-tree", colour: "ivory" },
  { template: "cc1717-woman-by-christmas-tree", colour: "crimson" },
  { template: "cc1717-hanging-on-fence", colour: "moss" },
];

/** Every tag must be held. An empty list keeps everything. */
export function hasTags(template: PickerTemplate, on: string[]): boolean {
  return on.every((tag) => template.tags.includes(tag));
}

