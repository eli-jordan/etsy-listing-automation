import bay from "../../assets/template-cards/fence-bay.jpg";
import berry from "../../assets/template-cards/fence-berry.jpg";
import blueJean from "../../assets/template-cards/folded-blue-jean.jpg";
import crimson from "../../assets/template-cards/folded-crimson.jpg";
import ivory from "../../assets/template-cards/folded-ivory.jpg";
import white from "../../assets/template-cards/folded-white.jpg";
import yam from "../../assets/template-cards/folded-yam.jpg";

/** One gallery entry as the card draws it: a mockup render, or a video
 * (drawn from its poster, with a play badge). Real 2048px square renders
 * from the try-workspace's mockup templates, downscaled. */
export interface GalleryItem {
  src: string;
  kind: "image" | "video";
  label: string;
}

export interface TemplateCardData {
  name: string;
  facts: string;
  usage: string;
  gallery: GalleryItem[];
}

const image = (src: string, label: string): GalleryItem => ({ src, kind: "image", label });

/** The seller's template from the screenshot, a two-image one and a
 * one-image one: a gallery layout has to hold up at every count. */
export const templates: TemplateCardData[] = [
  {
    name: "test-listing-template",
    facts: "Comfort Colors® 1717 · 5 colours · break-even-comfort-colors-1717",
    usage: "6 gallery items · No batches yet",
    gallery: [
      image(ivory, "ivory"),
      { src: bay, kind: "video", label: "size guide video" },
      image(white, "white"),
      image(yam, "yam"),
      image(crimson, "crimson"),
      image(blueJean, "blue-jean"),
    ],
  },
  {
    name: "fence-tee",
    facts: "Comfort Colors® 1717 · 2 colours · standard-tee",
    usage: "2 gallery images · Used by 3 batches",
    gallery: [image(bay, "bay"), image(berry, "berry")],
  },
  {
    name: "single-shot",
    facts: "Comfort Colors® 1717 · 1 colour · standard-tee",
    usage: "1 gallery image · Used by 1 batch",
    gallery: [image(white, "white")],
  },
];
