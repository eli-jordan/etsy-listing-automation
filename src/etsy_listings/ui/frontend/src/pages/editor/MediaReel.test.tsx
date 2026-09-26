import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { MediaFileSummary, MediaEntry } from "../../types";
import { MediaReel } from "./MediaReel";

/**
 * The reel, mounted on its own.
 *
 * The drag is the reason this is a module: the reel's order *is* the order Etsy
 * shows the images in, and the first tile is the shop thumbnail. Reaching these
 * handlers used to mean rendering the whole Listing Images tab with two mocked
 * endpoints behind it, so the drag was the part of the tab nothing exercised.
 */

const SIZING: MediaFileSummary = {
  name: "sizing.png",
  file: "common-media/sizing.png",
  ref: "common-media/sizing.png",
  kind: "image",
};

function reel(over: Partial<Parameters<typeof MediaReel>[0]> = {}) {
  const props = {
    media: [] as MediaEntry[],
    design: null,
    swatchTemplate: null,
    selectedIndex: null,
    listing: "take-a-hike" as string | null,
    files: [SIZING],
    onOpen: vi.fn(),
    onRemove: vi.fn(),
    onReorder: vi.fn(),
    onFocus: vi.fn(),
    ...over,
  };
  render(<MediaReel {...props} />);
  return props;
}

function tiles(): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>(".rtile"));
}

const INTRO: MediaFileSummary = {
  name: "intro.mp4",
  file: "common-media/intro.mp4",
  ref: "common-media/intro.mp4",
  kind: "video",
};

const THREE: MediaEntry[] = [
  { template: "flat-lay-01", colour: "black" },
  { template: "flat-lay-01", colour: "ivory" },
  SIZING.ref,
];

describe("MediaReel", () => {
  it("says how full the listing is against Etsy's ceiling", () => {
    reel({ media: THREE });
    expect(screen.getByText("3 of 20 images")).toBeTruthy();
    expect(screen.getByText("0 of 2 videos")).toBeTruthy();
  });

  it("counts images and videos apart, as Etsy caps them (PRD 71)", () => {
    reel({ media: [THREE[0] as MediaEntry, "common-media/intro.mp4", ...THREE.slice(1)] });
    expect(screen.getByText("3 of 20 images")).toBeTruthy();
    expect(screen.getByText("1 of 2 videos")).toBeTruthy();
  });

  it("draws one of the listing's own files from under that listing", () => {
    reel({ media: ["./shots/back.png"] });
    expect(screen.getByAltText("back")).toHaveAttribute(
      "src",
      "/api/listings/take-a-hike/media-files/shots/back.png/thumbnail",
    );
  });

  it("marks the first tile as the Etsy thumbnail, and only the first", () => {
    reel({ media: THREE });
    expect(screen.getAllByText("Etsy thumbnail")).toHaveLength(1);
  });

  it("invites a drag while there is room, and says what to do at the ceiling", () => {
    const media: MediaEntry[] = Array.from({ length: 20 }, (_, i) => `a-${i}.png`);
    reel({ media });
    expect(screen.getByText(/remove one before adding another/)).toBeTruthy();
  });

  it("says nothing is there yet for an empty listing", () => {
    reel();
    expect(screen.getByText(/Nothing here yet/)).toBeTruthy();
  });
});

/** Videos sit inline in the one reel, because `media:` is the gallery
 * (PRD 71): a muted clip showing its own frame, marked as a clip. */
describe("MediaReel's videos", () => {
  const GALLERY: MediaEntry[] = ["a.png", INTRO.ref, "b.png", "./close-up.mov"];

  function clip(index: number): HTMLVideoElement {
    const element = tiles()[index]?.querySelector("video");
    expect(element).toBeTruthy();
    return element as HTMLVideoElement;
  }

  it("draws a video as a muted, metadata-only clip resting on its poster frame", () => {
    reel({ media: GALLERY });
    const video = clip(1);
    expect(video).toHaveAttribute("src", "/api/common-media/intro.mp4/file#t=0.5");
    expect(video).toHaveAttribute("preload", "metadata");
    expect(video.muted).toBe(true);
    expect(tiles()[1]?.querySelector("img")).toBeNull();
    expect(clip(3)).toHaveAttribute(
      "src",
      "/api/listings/take-a-hike/media-files/close-up.mov/file#t=0.5",
    );
  });

  it("marks a video tile with a play badge", () => {
    reel({ media: GALLERY });
    expect(tiles().map((t) => t.querySelector(".rtile__play") !== null)).toEqual([
      false,
      true,
      false,
      true,
    ]);
  });

  it("labels the featured slot, where Etsy pins the first video", () => {
    reel({ media: GALLERY });
    expect(screen.getAllByText("Featured · shown 2nd")).toHaveLength(1);
    expect(tiles()[1]).toHaveTextContent("Featured · shown 2nd");
  });

  it("has no featured slot without a video", () => {
    reel({ media: THREE });
    expect(screen.queryByText("Featured · shown 2nd")).toBeNull();
  });

  it("plays a clip on hover and puts it back on its poster frame after", () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    const pause = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
    const props = reel({ media: GALLERY, files: [INTRO] });
    const face = document.querySelectorAll(".rtile__face")[1] as HTMLElement;

    fireEvent.mouseEnter(face);
    expect(play).toHaveBeenCalledTimes(1);
    expect(props.onFocus).toHaveBeenCalledWith({ kind: "file", asset: INTRO });

    fireEvent.mouseLeave(face);
    expect(pause).toHaveBeenCalledTimes(1);
    expect(clip(1).currentTime).toBe(0.5);
  });
});

describe("MediaReel's drag", () => {
  it("shows a drop the gallery rules refuse as refused, not as a landing place", () => {
    reel({ media: ["a.png", INTRO.ref, "b.png"] });
    const [first, second, third] = tiles();

    fireEvent.dragStart(third as HTMLElement);
    fireEvent.dragOver(first as HTMLElement);
    expect((first as HTMLElement).className).toContain("rtile--over");

    fireEvent.dragOver(second as HTMLElement);
    expect((second as HTMLElement).className).toContain("rtile--refused");
    expect((second as HTMLElement).className).not.toContain("rtile--over");
  });

  it("lets a video tile be carried", () => {
    const props = reel({ media: ["a.png", INTRO.ref, "b.png", "./close-up.mov"] });
    const [, second, , fourth] = tiles();

    fireEvent.dragStart(fourth as HTMLElement);
    fireEvent.dragOver(second as HTMLElement);
    fireEvent.drop(second as HTMLElement);

    expect(props.onReorder).toHaveBeenCalledWith(3, 1);
  });

  it("reports the move once the tile is dropped", () => {
    const props = reel({ media: THREE });
    const [first, , third] = tiles();

    fireEvent.dragStart(first as HTMLElement);
    fireEvent.dragOver(third as HTMLElement);
    fireEvent.drop(third as HTMLElement);

    expect(props.onReorder).toHaveBeenCalledWith(0, 2);
  });

  it("reports nothing for a drop with no drag behind it", () => {
    const props = reel({ media: THREE });
    fireEvent.drop(tiles()[1] as HTMLElement);
    expect(props.onReorder).not.toHaveBeenCalled();
  });

  it("clears the carried tile when the drag ends without a drop", () => {
    reel({ media: THREE });
    const first = tiles()[0] as HTMLElement;

    fireEvent.dragStart(first);
    expect(first.className).toContain("rtile--dragging");
    fireEvent.dragEnd(first);
    expect(first.className).not.toContain("rtile--dragging");
  });

  it("highlights the tile being dragged over, but never the carried one", () => {
    reel({ media: THREE });
    const [first, second] = tiles();

    fireEvent.dragStart(first as HTMLElement);
    fireEvent.dragOver(second as HTMLElement);
    expect((second as HTMLElement).className).toContain("rtile--over");

    fireEvent.dragOver(first as HTMLElement);
    expect((first as HTMLElement).className).not.toContain("rtile--over");
  });
});

describe("MediaReel's other clicks", () => {
  it("opens the carousel on a tile", () => {
    const props = reel({ media: THREE });
    fireEvent.click(document.querySelectorAll(".rtile__face")[1] as HTMLElement);
    expect(props.onOpen).toHaveBeenCalledWith(1);
  });

  it("removes without also opening the tile that slid into its place", () => {
    const props = reel({ media: THREE });
    fireEvent.click(screen.getByLabelText("Remove flat-lay-01 · ivory"));
    expect(props.onRemove).toHaveBeenCalledWith(1);
    expect(props.onOpen).not.toHaveBeenCalled();
  });

  it("previews a template tile on hover", () => {
    const props = reel({ media: THREE });
    fireEvent.mouseEnter(document.querySelectorAll(".rtile__face")[0] as HTMLElement);
    expect(props.onFocus).toHaveBeenCalledWith({
      kind: "template",
      template: "flat-lay-01",
      colour: "black",
    });
  });

  it("previews a shared tile on hover", () => {
    const props = reel({ media: THREE });
    fireEvent.mouseEnter(document.querySelectorAll(".rtile__face")[2] as HTMLElement);
    expect(props.onFocus).toHaveBeenCalledWith({ kind: "file", asset: SIZING });
  });

  it("stays silent for a ref whose file has gone from common-media/", () => {
    const props = reel({ media: ["common-media/deleted.png"], files: [SIZING] });
    fireEvent.mouseEnter(document.querySelectorAll(".rtile__face")[0] as HTMLElement);
    expect(props.onFocus).not.toHaveBeenCalled();
    expect(screen.getByText("deleted")).toBeTruthy();
  });

  it("marks the tile that supplies a colour's Etsy swatch", () => {
    reel({ media: THREE, swatchTemplate: "flat-lay-01" });
    expect(document.querySelectorAll(".rtile__swatch")).toHaveLength(2);
  });
});
