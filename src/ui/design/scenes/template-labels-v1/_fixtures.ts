import foldedHatLeaf from "../../assets/template-labels/folded-with-hat-and-leaf.jpg";
import hangingFence from "../../assets/template-labels/hanging-on-fence.jpg";
import hangingUmbrella from "../../assets/template-labels/hanging-under-umbrella.jpg";
import manSitting from "../../assets/template-labels/man-sitting-with-hat-and-glasses.jpg";
import manTiles from "../../assets/template-labels/man-with-sunglasses-against-blue-tiles.jpg";
import manTattoos from "../../assets/template-labels/man-with-tattoos-standing.jpg";
import redFlatLay from "../../assets/template-labels/red-shirt-flat-lay.jpg";
import womanTree from "../../assets/template-labels/woman-by-christmas-tree.jpg";
import womanBag from "../../assets/template-labels/woman-holding-a-bag.jpg";
import womanCardigan from "../../assets/template-labels/woman-in-cardigan-by-tree.jpg";
import womanElevator from "../../assets/template-labels/woman-in-elevator.jpg";
import womanSofa from "../../assets/template-labels/woman-on-white-sofa.jpg";
import womanCrossLegged from "../../assets/template-labels/woman-sitting-cross-legged.jpg";
import womanBlanket from "../../assets/template-labels/woman-with-mug-and-blanket.jpg";
import womanOversize from "../../assets/template-labels/woman-with-oversize-fit.jpg";
import womanPeace from "../../assets/template-labels/woman-with-peace-sign-and-mug.jpg";

export type GroupId = "shot" | "model" | "theme";

export interface LabelGroup {
  id: GroupId;
  title: string;
  options: string[];
  /** A template takes one value, or (for themes) as many as fit. */
  multiple: boolean;
}

export const groups: LabelGroup[] = [
  { id: "shot", title: "Shot", options: ["Flat lay", "Hanging", "On model"], multiple: false },
  { id: "model", title: "Model", options: ["Female", "Male", "Multiple people"], multiple: false },
  { id: "theme", title: "Theme", options: ["Christmas", "Summer", "Autumn", "Cosy"], multiple: true },
];

export interface LabelTemplate {
  name: string;
  src: string;
  labels: string[];
  status: "Ready" | "Needs maps";
}

/** The workspace's real templates. Labels are guesses from each photo, and
 * three are left bare to show what unlabelled looks like. */
export const templates: LabelTemplate[] = [
  { name: "cc1717-folded-with-hat-and-leaf", src: foldedHatLeaf, labels: ["Flat lay", "Autumn"], status: "Ready" },
  { name: "cc1717-hanging-on-fence", src: hangingFence, labels: ["Hanging"], status: "Ready" },
  { name: "cc1717-hanging-under-umbrella", src: hangingUmbrella, labels: ["Hanging", "Summer"], status: "Ready" },
  { name: "cc1717-man-sitting-with-hat-and-glasses", src: manSitting, labels: ["On model", "Male"], status: "Ready" },
  { name: "cc1717-man-with-sunglasses-against-blue-tiles", src: manTiles, labels: ["On model", "Male", "Summer"], status: "Ready" },
  { name: "cc1717-man-with-tattoos-standing", src: manTattoos, labels: [], status: "Ready" },
  { name: "cc1717-red-shirt-flat-lay", src: redFlatLay, labels: ["Flat lay", "Christmas"], status: "Needs maps" },
  { name: "cc1717-woman-by-christmas-tree", src: womanTree, labels: ["On model", "Female", "Christmas"], status: "Ready" },
  { name: "cc1717-woman-holding-a-bag", src: womanBag, labels: [], status: "Ready" },
  { name: "cc1717-woman-in-cardigan-by-tree", src: womanCardigan, labels: ["On model", "Female", "Christmas"], status: "Ready" },
  { name: "cc1717-woman-in-elevator", src: womanElevator, labels: [], status: "Ready" },
  { name: "cc1717-woman-on-white-sofa", src: womanSofa, labels: ["On model", "Female", "Christmas"], status: "Ready" },
  { name: "cc1717-woman-sitting-cross-legged", src: womanCrossLegged, labels: ["On model", "Female"], status: "Ready" },
  { name: "cc1717-woman-with-mug-and-blanket", src: womanBlanket, labels: ["On model", "Female", "Cosy"], status: "Ready" },
  { name: "cc1717-woman-with-oversize-fit", src: womanOversize, labels: ["On model", "Female"], status: "Ready" },
  { name: "cc1717-woman-with-peace-sign-and-mug", src: womanPeace, labels: ["On model", "Female", "Christmas"], status: "Ready" },
];

export type Selection = Partial<Record<GroupId, string[]>>;

/** Any choice within a group, every group with a choice. `except` leaves one
 * group out, which is how a facet counts what ticking it would give. */
export function matches(template: LabelTemplate, selection: Selection, except?: GroupId): boolean {
  return groups.every((group) => {
    const chosen = selection[group.id] ?? [];
    if (group.id === except || chosen.length === 0) return true;
    return chosen.some((label) => template.labels.includes(label));
  });
}

/** The label a template holds in a group: at most one, except for themes. */
export function labelsIn(template: LabelTemplate, group: LabelGroup): string[] {
  return template.labels.filter((label) => group.options.includes(label));
}

/** A flat lay has no model on purpose; a bare cell means nobody has said. */
export function hasNoModel(template: LabelTemplate): boolean {
  return template.labels.includes("Flat lay") || template.labels.includes("Hanging");
}

/** Saying who is modelling already says the shot, so one choice sets both. */
export function withImpliedShot(labels: string[]): string[] {
  const modelled = ["Female", "Male", "Multiple people"].some((l) => labels.includes(l));
  const shot = ["Flat lay", "Hanging", "On model"].some((l) => labels.includes(l));
  return modelled && !shot ? ["On model", ...labels] : labels;
}
