import { describe, expect, it } from "vitest";
import type { ListingDetail } from "../../types";
import { mediaLostBy, selectColours, selectGarmentProfile } from "./colourSelection";
import { listingDetail } from "../../test/listings";

/** Pure, so the cascade is tested here rather than through a rendered tab --
 * what the Variants tab's own tests check is that it goes through this. */

function detail(over: Partial<ListingDetail> = {}): ListingDetail {
  return listingDetail({ design: {}, colors: ["black", "white"], ...over });
}

describe("selectColours", () => {
  it("patches colors alone when nothing was dropped", () => {
    expect(selectColours(detail(), ["black", "white", "navy"])).toEqual({
      colors: ["black", "white", "navy"],
    });
  });

  it("drops media entries for a colour that is no longer sold", () => {
    const patch = selectColours(
      detail({
        media: [
          { template: "flat-lay-01", colour: "black" },
          { template: "flat-lay-01", colour: "white" },
        ],
      }),
      ["black"],
    );
    expect(patch.media).toEqual([{ template: "flat-lay-01", colour: "black" }]);
  });

  it("brings the next image forward when the thumbnail's colour goes, keeping the video 2nd", () => {
    /* Left as filtered, the video became position 1, a document the server
       refuses -- and the whole colour change with it. */
    const patch = selectColours(
      detail({
        media: [
          { template: "flat-lay-01", colour: "white" },
          "common-media/size-guide.mp4",
          "common-media/size-chart.png",
          { template: "flat-lay-01", colour: "black" },
        ],
      }),
      ["black"],
    );
    expect(patch.media).toEqual([
      "common-media/size-chart.png",
      "common-media/size-guide.mp4",
      { template: "flat-lay-01", colour: "black" },
    ]);
  });

  it("drops the videos too when no image is left to be the thumbnail", () => {
    const patch = selectColours(
      detail({ media: [{ template: "flat-lay-01", colour: "white" }, "common-media/clip.mp4"] }),
      ["black"],
    );
    expect(patch.media).toEqual([]);
  });

  it("keeps entries with no colour of their own", () => {
    /* A `multiple`/`single` template has one output and no colour, and a
       shared asset is a bare path -- neither is about a variant, so dropping
       every colour leaves both alone (and `media` out of the patch, since
       there is nothing about it to change). */
    const media = [{ template: "sizing-chart", colour: null }, "common-media/care.png"];
    const listing = detail({ media });
    expect("media" in selectColours(listing, [])).toBe(false);
    expect(mediaLostBy(listing, [])).toBe(0);
  });

  it("drops a colour's own design and price overrides too", () => {
    const patch = selectColours(
      detail({
        design: { default: "designs/a.png", white: "designs/w.png", black: "designs/b.png" },
        price_overrides: { white: { S: "399 NOK" } },
      }),
      ["black"],
    );
    expect(patch.design).toEqual({ default: "designs/a.png", black: "designs/b.png" });
    expect(patch.price_overrides).toEqual({});
  });

  it("leaves a colour-keyed field out of the patch when it had nothing to lose", () => {
    /* Rewriting a field to itself is a change the server would store and the
       next reader would have to reason about. */
    const patch = selectColours(
      detail({ design: { default: "designs/a.png", black: "designs/b.png" } }),
      ["black"],
    );
    expect("design" in patch).toBe(false);
    expect("media" in patch).toBe(false);
  });

  it("counts what a bulk change would throw away", () => {
    const listing = detail({
      media: [
        { template: "flat-lay-01", colour: "black" },
        { template: "flat-lay-01", colour: "white" },
        "common-media/care.png",
      ],
    });
    expect(mediaLostBy(listing, ["black"])).toBe(1);
    expect(mediaLostBy(listing, ["black", "white"])).toBe(0);
  });
});

describe("selectGarmentProfile", () => {
  it("enables every colour the profile classifies", () => {
    /* Picking a garment on a new listing (empty colors:) is the ordinary
       case; the action is the same when switching garments. */
    expect(selectGarmentProfile(detail({ colors: [] }), "gildan-5000", ["black", "ivory"])).toEqual(
      {
        garment_profile: "gildan-5000",
        colors: ["black", "ivory"],
      },
    );
  });

  it("drops mockups for colours the new profile does not sell", () => {
    const listing = detail({
      garment_profile: "comfort-colors-1717",
      colors: ["black", "white"],
      media: [
        { template: "flat-lay-01", colour: "black" },
        { template: "flat-lay-01", colour: "white" },
      ],
    });
    expect(selectGarmentProfile(listing, "gildan-5000", ["black"])).toEqual({
      garment_profile: "gildan-5000",
      colors: ["black"],
      media: [{ template: "flat-lay-01", colour: "black" }],
    });
  });

  it("keeps a colour's own design the new profile sells, and drops the rest", () => {
    /* Spec, *Colour-specific artwork*: changing garment profile preserves
       colour keys that exist in the new profile and removes the rest. */
    const listing = detail({
      colors: ["black", "moss", "white"],
      design: {
        "on-light": "designs/dark-ink.png",
        "on-dark": "designs/light-ink.png",
        moss: "designs/moss.png",
        white: "designs/white.png",
      },
    });
    expect(selectGarmentProfile(listing, "gildan-5000", ["black", "ivory", "moss"])).toEqual({
      garment_profile: "gildan-5000",
      colors: ["black", "ivory", "moss"],
      design: {
        "on-light": "designs/dark-ink.png",
        "on-dark": "designs/light-ink.png",
        moss: "designs/moss.png",
      },
    });
  });
});
