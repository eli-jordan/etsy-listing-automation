import { describe, expect, it } from "vitest";
import type { CommonMediaSummary, ListingDetail, MediaEntry, TemplateSummary } from "../../types";
import { type Focus, viewFocus } from "./focus";

/**
 * What the preview pane is pointing at.
 *
 * The question worth isolating is `inListing`: the locator can point the
 * preview at something the listing has *not* taken, and the Add/Remove button,
 * the lightbox and the pane's title each turned on that answer separately
 * before this module existed.
 */

const FLAT_LAY: TemplateSummary = {
  name: "flat-lay-01",
  kind: "colour-matrix",
  colours: ["black"],
  photos: [{ colour: "black", file: "mockup-templates/flat-lay-01/black.png" }],
  has_config: true,
  status: "calibrated",
  status_reason: null,
};

const SIZING: CommonMediaSummary = {
  name: "sizing",
  file: "common-media/sizing.png",
  ref: "common-media/sizing.png",
};

function listing(media: MediaEntry[]): ListingDetail {
  return { media } as ListingDetail;
}

const ON_TEMPLATE: Focus = { kind: "template", template: "flat-lay-01", colour: "black" };
const ON_SHARED: Focus = { kind: "shared", asset: SIZING };

describe("viewFocus, for a template", () => {
  it("reports it as in the listing when media carries it", () => {
    const view = viewFocus(
      ON_TEMPLATE,
      listing([{ template: "flat-lay-01", colour: "black" }]),
      [FLAT_LAY],
      null,
    );
    expect(view.inListing).toBe(true);
    expect(view.reelIndex).toBe(0);
  });

  it("reports -1 for something the locator is only offering", () => {
    const view = viewFocus(ON_TEMPLATE, listing([]), [FLAT_LAY], null);
    expect(view.inListing).toBe(false);
    expect(view.reelIndex).toBe(-1);
  });

  it("captions it with the file the server resolved", () => {
    const view = viewFocus(ON_TEMPLATE, listing([]), [FLAT_LAY], null);
    expect(view.path).toBe("mockup-templates/flat-lay-01/black.png");
  });

  it("falls back to the convention for a template not in the loaded list", () => {
    const view = viewFocus(ON_TEMPLATE, listing([]), [], null);
    expect(view.path).toBe("mockup-templates/flat-lay-01/black.png");
  });

  it("titles it with the template and colour", () => {
    expect(viewFocus(ON_TEMPLATE, listing([]), [FLAT_LAY], null).title).toBe("flat-lay-01 · black");
  });

  it("composites the design into the picture when there is one", () => {
    const view = viewFocus(ON_TEMPLATE, listing([]), [FLAT_LAY], "take-a-hike");
    expect(view.picture).toContain("design-preview");
  });
});

describe("viewFocus, for a shared asset", () => {
  it("finds its position in the reel", () => {
    const view = viewFocus(ON_SHARED, listing(["a.png", SIZING.ref]), [], null);
    expect(view.inListing).toBe(true);
    expect(view.reelIndex).toBe(1);
  });

  it("reports -1 when the listing has not taken it", () => {
    const view = viewFocus(ON_SHARED, listing([]), [], null);
    expect(view.inListing).toBe(false);
    expect(view.reelIndex).toBe(-1);
  });

  it("captions it with the workspace path the server already gave", () => {
    expect(viewFocus(ON_SHARED, listing([]), [], null).path).toBe("common-media/sizing.png");
  });

  it("shows the file itself, never a render -- it is already what Etsy gets", () => {
    const view = viewFocus(ON_SHARED, listing([]), [], "take-a-hike");
    expect(view.picture).toBe("/api/common-media/sizing/file");
  });
});
