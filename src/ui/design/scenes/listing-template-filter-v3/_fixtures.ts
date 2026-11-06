import { templates as labelled } from "../template-labels/_fixtures";

export const LISTING = "santa-cookie-crew";
export const COLOURS = ["ivory", "crimson", "moss", "black"];
/** The listing's own words, which direction C reads for suggestions. */
export const LISTING_TITLE = "Santa Cookie Crew Christmas T-Shirt";

export interface PickerTemplate {
  name: string;
  src: string;
  tags: string[];
}

/** Direction A's free-form tags, as the Mockup Templates page would save them. */
function asTag(label: string): string | null {
  if (label === "On model") return null;
  if (label === "Female" || label === "Male") return `${label.toLowerCase()} model`;
  return label.toLowerCase();
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

