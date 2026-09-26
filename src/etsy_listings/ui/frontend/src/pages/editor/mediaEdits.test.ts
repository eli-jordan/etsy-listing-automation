import { describe, expect, it } from "vitest";
import type { MediaEntry } from "../../types";
import {
  MAX_IMAGES,
  MAX_VIDEOS,
  type MediaState,
  addEveryMissingColour,
  canReorder,
  removeAt,
  reorder,
  roomLeft,
  toggleEntry,
  toggleFile,
  toggleSwatchSource,
} from "./mediaEdits";

/**
 * The rules about what a listing's `media:` may contain, called directly.
 *
 * Every one of these used to need a rendered `ImagesTab`, a mocked
 * `GET /api/templates`, a mocked `GET /api/common-media` and a full 28-field
 * `ListingDetail` -- to assert something that is a list transformation.
 */

function state(over: Partial<MediaState> = {}): MediaState {
  return {
    media: [],
    colors: ["black", "ivory"],
    etsy: {},
    ...over,
  };
}

function entries(patch: Record<string, unknown> | null): MediaEntry[] {
  expect(patch).not.toBeNull();
  return (patch as { media: MediaEntry[] }).media;
}

describe("toggleEntry", () => {
  it("adds a template/colour that is not there", () => {
    const patch = toggleEntry(state(), "flat-lay-01", "black");
    expect(entries(patch)).toEqual([{ template: "flat-lay-01", colour: "black" }]);
  });

  it("removes the one that is", () => {
    const media = [{ template: "flat-lay-01", colour: "black" }];
    expect(entries(toggleEntry(state({ media }), "flat-lay-01", "black"))).toEqual([]);
  });

  it("treats an absent colour and an explicit null as the same entry", () => {
    const media: MediaEntry[] = [{ template: "rack-shot", colour: null }];
    expect(entries(toggleEntry(state({ media }), "rack-shot", null))).toEqual([]);
  });

  it("leaves other colours of the same template alone", () => {
    const media = [
      { template: "flat-lay-01", colour: "black" },
      { template: "flat-lay-01", colour: "ivory" },
    ];
    expect(entries(toggleEntry(state({ media }), "flat-lay-01", "black"))).toEqual([
      { template: "flat-lay-01", colour: "ivory" },
    ]);
  });

  it("declines rather than writing a twenty-first image", () => {
    const media = Array.from({ length: MAX_IMAGES }, (_, i) => `common-media/${i}.png`);
    expect(toggleEntry(state({ media }), "flat-lay-01", "black")).toBeNull();
  });

  it("still removes at the ceiling", () => {
    const media: MediaEntry[] = Array.from({ length: MAX_IMAGES - 1 }, (_, i) => `a-${i}.png`);
    media.push({ template: "flat-lay-01", colour: "black" });
    expect(entries(toggleEntry(state({ media }), "flat-lay-01", "black"))).toHaveLength(
      MAX_IMAGES - 1,
    );
  });
});

describe("toggleFile", () => {
  it("stores a listing's own file as its ./ ref", () => {
    expect(entries(toggleFile(state(), "./shots/back.png"))).toEqual(["./shots/back.png"]);
  });

  it("stores a shared asset as the bare ref, not an entry object", () => {
    const patch = toggleFile(state(), "common-media/sizing.png");
    expect(entries(patch)).toEqual(["common-media/sizing.png"]);
  });

  it("removes it again", () => {
    const media = ["common-media/sizing.png"];
    expect(entries(toggleFile(state({ media }), "common-media/sizing.png"))).toEqual([]);
  });

  it("declines at the ceiling", () => {
    const media = Array.from({ length: MAX_IMAGES }, (_, i) => `a-${i}.png`);
    expect(toggleFile(state({ media }), "common-media/sizing.png")).toBeNull();
  });
});

describe("addEveryMissingColour", () => {
  it("adds one entry per colour the listing sells and the reel lacks", () => {
    const media = [{ template: "flat-lay-01", colour: "black" }];
    const patch = addEveryMissingColour(state({ media }), "flat-lay-01");
    expect(entries(patch)).toEqual([
      { template: "flat-lay-01", colour: "black" },
      { template: "flat-lay-01", colour: "ivory" },
    ]);
  });

  it("declines when there is nothing missing", () => {
    const media = [
      { template: "flat-lay-01", colour: "black" },
      { template: "flat-lay-01", colour: "ivory" },
    ];
    expect(addEveryMissingColour(state({ media }), "flat-lay-01")).toBeNull();
  });

  it("stops at the ceiling rather than adding all of them", () => {
    const colors = Array.from({ length: 30 }, (_, i) => `colour-${i}`);
    const patch = addEveryMissingColour(state({ colors }), "flat-lay-01");
    expect(entries(patch)).toHaveLength(MAX_IMAGES);
  });
});

describe("toggleSwatchSource (PRD 56)", () => {
  it("adds the colours the template lacks, because the engine refuses a gap", () => {
    const patch = toggleSwatchSource(state(), "flat-lay-01");
    expect(patch).toEqual({
      media: [
        { template: "flat-lay-01", colour: "black" },
        { template: "flat-lay-01", colour: "ivory" },
      ],
      etsy: { variation_images: "flat-lay-01" },
    });
  });

  it("turns it off without touching the images", () => {
    const media = [{ template: "flat-lay-01", colour: "black" }];
    const patch = toggleSwatchSource(
      state({ media, etsy: { variation_images: "flat-lay-01" } }),
      "flat-lay-01",
    );
    expect(patch).toEqual({ etsy: { variation_images: null } });
  });

  it("switching source clears the old one, since there is only one", () => {
    const patch = toggleSwatchSource(
      state({ etsy: { variation_images: "rack-shot" } }),
      "flat-lay-01",
    );
    expect(patch["etsy"]).toEqual({ variation_images: "flat-lay-01" });
  });

  it("adds nothing when the colours are already covered", () => {
    const media = [
      { template: "flat-lay-01", colour: "black" },
      { template: "flat-lay-01", colour: "ivory" },
    ];
    expect(entries(toggleSwatchSource(state({ media }), "flat-lay-01"))).toEqual(media);
  });

  it("cannot push the listing past the ceiling to cover a colour", () => {
    const colors = Array.from({ length: 30 }, (_, i) => `colour-${i}`);
    expect(entries(toggleSwatchSource(state({ colors }), "flat-lay-01"))).toHaveLength(MAX_IMAGES);
  });
});

describe("reorder", () => {
  const media = ["a.png", "b.png", "c.png"];

  it("moves a tile later", () => {
    expect(entries(reorder(state({ media }), 0, 2))).toEqual(["b.png", "c.png", "a.png"]);
  });

  it("moves a tile earlier", () => {
    expect(entries(reorder(state({ media }), 2, 0))).toEqual(["c.png", "a.png", "b.png"]);
  });

  it("declines a drop on the tile's own position", () => {
    expect(reorder(state({ media }), 1, 1)).toBeNull();
  });

  it("declines a drag from an index that is not there", () => {
    expect(reorder(state({ media }), 9, 0)).toBeNull();
  });
});

describe("removeAt", () => {
  it("drops exactly one tile, by position", () => {
    const media = ["a.png", "a.png", "b.png"];
    expect(entries(removeAt(state({ media }), 0))).toEqual(["a.png", "b.png"]);
  });
});

describe("roomLeft", () => {
  it("never goes negative for a listing already over the ceiling", () => {
    const media = Array.from({ length: MAX_IMAGES + 3 }, (_, i) => `a-${i}.png`);
    expect(roomLeft(media)).toBe(0);
  });
});

/**
 * The gallery rules, as `config/listing.py`'s `_check_gallery` states them
 * (PRD 71): position 1 is an image, any video puts one at position 2, at most
 * two videos, and images and videos have separate caps. A click never writes
 * a gallery the server would refuse.
 */
describe("the gallery rules (PRD 71)", () => {
  const IMG = "common-media/sizing.png";
  const CLIP = "common-media/intro.mp4";
  const LOCAL = "./close-up.MOV";

  it("puts a first video at position 2, behind the thumbnail", () => {
    const media = ["a.png", "b.png", "c.png"];
    expect(entries(toggleFile(state({ media }), CLIP))).toEqual(["a.png", CLIP, "b.png", "c.png"]);
  });

  it("puts a first video at position 2 when the thumbnail is a render", () => {
    const media = [{ template: "flat-lay-01", colour: "black" }];
    expect(entries(toggleFile(state({ media }), CLIP))).toEqual([...media, CLIP]);
  });

  it("appends a second video, anywhere after the first being allowed", () => {
    const media = ["a.png", CLIP, "b.png"];
    expect(entries(toggleFile(state({ media }), LOCAL))).toEqual(["a.png", CLIP, "b.png", LOCAL]);
  });

  it("refuses a third video", () => {
    const media = ["a.png", CLIP, "b.png", LOCAL];
    expect(MAX_VIDEOS).toBe(2);
    expect(toggleFile(state({ media }), "./third.mp4")).toBeNull();
  });

  it("refuses a video before there is an image to be the thumbnail", () => {
    expect(toggleFile(state(), CLIP)).toBeNull();
  });

  it("counts images and videos apart: a video still fits beside twenty images", () => {
    const media = Array.from({ length: MAX_IMAGES }, (_, i) => `a-${i}.png`);
    expect(entries(toggleFile(state({ media }), CLIP))).toHaveLength(MAX_IMAGES + 1);
  });

  it("counts images and videos apart: videos take no image slot", () => {
    const media = [
      "a-0.png",
      CLIP,
      LOCAL,
      ...Array.from({ length: MAX_IMAGES - 2 }, (_, i) => `a-${i + 1}.png`),
    ];
    expect(roomLeft(media)).toBe(1);
    expect(entries(toggleFile(state({ media }), IMG))).toHaveLength(MAX_IMAGES + 2);
    expect(entries(toggleEntry(state({ media }), "flat-lay-01", "black"))).toHaveLength(
      MAX_IMAGES + 2,
    );
  });

  it("promotes the second video to position 2 when the featured one is removed, as Etsy does", () => {
    const media = ["a.png", CLIP, "b.png", LOCAL];
    expect(entries(toggleFile(state({ media }), CLIP))).toEqual(["a.png", LOCAL, "b.png"]);
    expect(entries(removeAt(state({ media }), 1))).toEqual(["a.png", LOCAL, "b.png"]);
  });

  it("brings the next image forward when the thumbnail is removed", () => {
    const media = ["a.png", CLIP, "b.png", LOCAL];
    expect(entries(removeAt(state({ media }), 0))).toEqual(["b.png", CLIP, LOCAL]);
  });

  it("brings the next image forward when the thumbnail is a template entry", () => {
    const media: MediaEntry[] = [{ template: "flat-lay-01", colour: "black" }, CLIP, IMG];
    expect(entries(toggleEntry(state({ media }), "flat-lay-01", "black"))).toEqual([IMG, CLIP]);
  });

  it("refuses to remove the last image while a video remains -- nothing could be the thumbnail", () => {
    const media = ["a.png", CLIP];
    expect(toggleFile(state({ media }), "a.png")).toBeNull();
    expect(removeAt(state({ media }), 0)).toBeNull();
  });

  it("leaves a gallery with no video exactly as the removal left it", () => {
    const media = ["a.png", "b.png", "c.png"];
    expect(entries(removeAt(state({ media }), 0))).toEqual(["b.png", "c.png"]);
  });
});

/**
 * A drag inside the same rules. A move either lands a gallery
 * `_check_gallery` accepts or is no move at all -- the tile snaps back.
 */
describe("reorder, within the gallery rules (PRD 71)", () => {
  const CLIP = "common-media/intro.mp4";
  const LOCAL = "./close-up.MOV";

  it("moves the second video among the images", () => {
    const media = ["a.png", CLIP, "b.png", "c.png", LOCAL];
    expect(entries(reorder(state({ media }), 4, 2))).toEqual([
      "a.png",
      CLIP,
      LOCAL,
      "b.png",
      "c.png",
    ]);
    expect(canReorder(media, 4, 2)).toBe(true);
  });

  it("swaps the videos by dropping the second on the featured slot", () => {
    const media = ["a.png", CLIP, "b.png", LOCAL];
    expect(entries(reorder(state({ media }), 3, 1))).toEqual(["a.png", LOCAL, CLIP, "b.png"]);
  });

  it("lets another image become the thumbnail, the featured video staying 2nd", () => {
    const media = ["a.png", CLIP, "b.png"];
    expect(entries(reorder(state({ media }), 2, 0))).toEqual(["b.png", CLIP, "a.png"]);
  });

  it("moves the thumbnail behind the featured video, which stays 2nd", () => {
    const media = ["a.png", CLIP, "b.png", "c.png"];
    expect(entries(reorder(state({ media }), 0, 2))).toEqual(["b.png", CLIP, "a.png", "c.png"]);
  });

  it("moves images among images around the featured video", () => {
    const media = ["a.png", CLIP, "b.png", "c.png"];
    expect(entries(reorder(state({ media }), 3, 2))).toEqual(["a.png", CLIP, "c.png", "b.png"]);
  });

  it("snaps back a video dropped on the thumbnail", () => {
    const media = ["a.png", CLIP, "b.png", LOCAL];
    expect(reorder(state({ media }), 3, 0)).toBeNull();
    expect(canReorder(media, 3, 0)).toBe(false);
  });

  it("snaps back the only image dragged behind both videos -- the second would be the thumbnail", () => {
    expect(reorder(state({ media: ["a.png", CLIP, LOCAL] }), 0, 2)).toBeNull();
  });

  it("snaps back the thumbnail dropped on the featured slot", () => {
    expect(reorder(state({ media: ["a.png", CLIP, "b.png"] }), 0, 1)).toBeNull();
  });

  it("snaps back an image dropped on the featured slot", () => {
    expect(reorder(state({ media: ["a.png", CLIP, "b.png"] }), 2, 1)).toBeNull();
  });

  it("snaps back the featured video dragged past an image", () => {
    expect(reorder(state({ media: ["a.png", CLIP, "b.png", LOCAL] }), 1, 2)).toBeNull();
  });

  it("allows nothing for a move that is no move", () => {
    expect(canReorder(["a.png", "b.png"], 1, 1)).toBe(false);
    expect(canReorder(["a.png", "b.png"], 5, 0)).toBe(false);
  });
});
