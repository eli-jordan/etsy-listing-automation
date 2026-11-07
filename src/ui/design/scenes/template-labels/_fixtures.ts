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

/** The fixture labels as saved tags. Cosy stays plain to show the Other group. */
export function asTag(label: string): string | null {
  const tags: Record<string, string | null> = {
    "On model": null,
    "Flat lay": "shot:flat lay",
    Hanging: "shot:hanging",
    Female: "model:female",
    Male: "model:male",
    Christmas: "theme:christmas",
    Summer: "theme:summer",
    Autumn: "theme:autumn",
    Cosy: "cosy",
  };
  return tags[label] ?? null;
}
