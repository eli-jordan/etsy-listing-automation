import { describe, expect, it } from "vitest";
import type { MediaEntry } from "../../types";
import {
  MAX_MEDIA,
  type MediaState,
  addEveryMissingColour,
  removeAt,
  reorder,
  roomLeft,
  toggleEntry,
  toggleShared,
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
    const media = Array.from({ length: MAX_MEDIA }, (_, i) => `common-media/${i}.png`);
    expect(toggleEntry(state({ media }), "flat-lay-01", "black")).toBeNull();
  });

  it("still removes at the ceiling", () => {
    const media: MediaEntry[] = Array.from({ length: MAX_MEDIA - 1 }, (_, i) => `a-${i}.png`);
    media.push({ template: "flat-lay-01", colour: "black" });
    expect(entries(toggleEntry(state({ media }), "flat-lay-01", "black"))).toHaveLength(
      MAX_MEDIA - 1,
    );
  });
});

describe("toggleShared", () => {
  it("stores a shared asset as the bare ref, not an entry object", () => {
    const patch = toggleShared(state(), "common-media/sizing.png");
    expect(entries(patch)).toEqual(["common-media/sizing.png"]);
  });

  it("removes it again", () => {
    const media = ["common-media/sizing.png"];
    expect(entries(toggleShared(state({ media }), "common-media/sizing.png"))).toEqual([]);
  });

  it("declines at the ceiling", () => {
    const media = Array.from({ length: MAX_MEDIA }, (_, i) => `a-${i}.png`);
    expect(toggleShared(state({ media }), "common-media/sizing.png")).toBeNull();
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
    expect(entries(patch)).toHaveLength(MAX_MEDIA);
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
    expect(entries(toggleSwatchSource(state({ colors }), "flat-lay-01"))).toHaveLength(MAX_MEDIA);
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
    const media = Array.from({ length: MAX_MEDIA + 3 }, (_, i) => `a-${i}.png`);
    expect(roomLeft(media)).toBe(0);
  });
});
