import { describe, expect, it } from "vitest";
import {
  isInMedia,
  mediaKind,
  mediaLabel,
  missingColours,
  pictureFor,
  refName,
  scenePath,
  singleDesignName,
  templatePicture,
} from "./media";
import type { MediaEntry, TemplateSummary } from "./types";

/**
 * What `media:` holds, and what it looks like.
 *
 * These answers used to be spread across whichever tab first needed them --
 * three regexes for "strip the directory and the extension", and two
 * `design ? preview : photo` branches with different fallback orders. The
 * `pictureFor` cases below are what a single owner buys: one place to state
 * which endpoint answers which question.
 */

const FLAT_LAY: TemplateSummary = {
  name: "flat-lay-01",
  kind: "colour-matrix",
  colours: ["black", "ivory"],
  photos: [
    { colour: "black", file: "mockup-templates/flat-lay-01/black.png" },
    { colour: "ivory", file: "mockup-templates/flat-lay-01/ivory.png" },
  ],
  has_config: true,
  status: "calibrated",
  status_reason: null,
};

describe("refName", () => {
  it("takes the stem of a ref", () => {
    expect(refName("common-media/sizing-chart.png")).toBe("sizing-chart");
  });

  it("takes the stem of a bare filename", () => {
    expect(refName("sizing-chart.png")).toBe("sizing-chart");
  });

  it("keeps a name with no extension", () => {
    expect(refName("common-media/README")).toBe("README");
  });

  it("strips only the last extension, so a dotted name survives", () => {
    expect(refName("designs/take-a-hike.v2.png")).toBe("take-a-hike.v2");
  });
});

describe("singleDesignName", () => {
  it("names the one design", () => {
    expect(singleDesignName({ default: "designs/take-a-hike.png" })).toBe("take-a-hike");
  });

  it("answers null for a multi-artwork listing, which has no single design", () => {
    expect(
      singleDesignName({ "on-light": "designs/a.png", "on-dark": "designs/b.png" }),
    ).toBeNull();
  });

  it("answers null for a listing with no design at all", () => {
    expect(singleDesignName({})).toBeNull();
  });
});

describe("mediaLabel", () => {
  it("labels a colour-matrix entry with its template and colour", () => {
    expect(mediaLabel({ template: "flat-lay-01", colour: "black" })).toBe("flat-lay-01 · black");
  });

  it("labels a fixed-scene entry with the template alone", () => {
    expect(mediaLabel({ template: "rack-shot", colour: null })).toBe("rack-shot");
  });

  it("labels a shared asset by its filename", () => {
    expect(mediaLabel("common-media/sizing.png")).toBe("sizing");
  });
});

describe("isInMedia", () => {
  const media: MediaEntry[] = [
    "common-media/sizing.png",
    { template: "flat-lay-01", colour: "black" },
    { template: "rack-shot", colour: null },
  ];

  it("finds a template/colour pair", () => {
    expect(isInMedia(media, "flat-lay-01", "black")).toBe(true);
  });

  it("does not match a different colour of the same template", () => {
    expect(isInMedia(media, "flat-lay-01", "ivory")).toBe(false);
  });

  it("matches a fixed scene by a null colour", () => {
    expect(isInMedia(media, "rack-shot", null)).toBe(true);
  });

  it("never matches a shared asset", () => {
    expect(isInMedia(media, "common-media/sizing.png", null)).toBe(false);
  });
});

describe("missingColours", () => {
  it("is driven by what the listing sells, not by the template's photos", () => {
    const media = [{ template: "flat-lay-01", colour: "black" }];
    expect(missingColours(media, ["black", "ivory", "moss"], "flat-lay-01")).toEqual([
      "ivory",
      "moss",
    ]);
  });
});

describe("pictureFor", () => {
  it("composites the listing's real design onto a template at full size", () => {
    const url = pictureFor({ template: "flat-lay-01", colour: "black" }, "take-a-hike");
    expect(url).toContain("/api/templates/flat-lay-01/design-preview");
    expect(url).toContain("design=take-a-hike");
    expect(url).toContain("colour=black");
  });

  it("falls back to the bare photo when there is no single design to composite", () => {
    const url = pictureFor({ template: "flat-lay-01", colour: "black" }, null);
    expect(url).toBe("/api/templates/flat-lay-01/photo?colour=black");
  });

  it("uses the thumbnail for a tile, never a render", () => {
    const url = pictureFor({ template: "flat-lay-01", colour: "black" }, "take-a-hike", "tile");
    expect(url).toBe("/api/templates/flat-lay-01/thumbnail?colour=black");
  });

  it("keeps the colour on a tile, or a reel of one set draws eight identical pictures", () => {
    const black = pictureFor({ template: "flat-lay-01", colour: "black" }, null, "tile");
    const ivory = pictureFor({ template: "flat-lay-01", colour: "ivory" }, null, "tile");
    expect(black).not.toBe(ivory);
  });

  it("serves a shared asset as-is at full size -- it is already what Etsy gets", () => {
    expect(pictureFor("common-media/sizing.png", "take-a-hike")).toBe(
      "/api/common-media/sizing.png/file",
    );
  });

  it("addresses a shared asset by its full path under common-media/, extension and all", () => {
    /* A shared file may be a JPEG, and may sit in a subdirectory (PRD 72):
       the stem alone cannot say which file it is. */
    expect(pictureFor("common-media/charts/care.jpg", null)).toBe(
      "/api/common-media/charts/care.jpg/file",
    );
  });

  it("escapes each segment of a shared asset's path, but not the slashes between", () => {
    expect(pictureFor("common-media/a b/c#d.png", null, "tile")).toBe(
      "/api/common-media/a%20b/c%23d.png/thumbnail",
    );
  });

  it("serves a shared asset's thumbnail for a tile", () => {
    expect(pictureFor("common-media/sizing.png", null, "tile")).toBe(
      "/api/common-media/sizing.png/thumbnail",
    );
  });

  it("omits the colour for a fixed-scene template", () => {
    expect(pictureFor({ template: "rack-shot", colour: null }, null)).toBe(
      "/api/templates/rack-shot/photo",
    );
  });

  it("encodes a name that would otherwise break the path", () => {
    expect(pictureFor({ template: "a/b", colour: null }, null)).toContain("a%2Fb");
  });
});

describe("pictureFor a video or a listing's own file", () => {
  it("serves a video's file even for a tile -- the browser draws its poster, there is no thumbnail", () => {
    expect(pictureFor("common-media/videos/intro.mp4", null, "tile")).toBe(
      "/api/common-media/videos/intro.mp4/file",
    );
  });

  it("addresses a ./ ref under the listing it belongs to", () => {
    expect(pictureFor("./shots/back.png", null, "tile", "take-a-hike")).toBe(
      "/api/listings/take-a-hike/media-files/shots/back.png/thumbnail",
    );
    expect(pictureFor("./close-up.MOV", null, "full", "take a hike")).toBe(
      "/api/listings/take%20a%20hike/media-files/close-up.MOV/file",
    );
  });

  it("has no picture for a ./ ref when there is no listing directory to find it in", () => {
    /* The editor's unnamed draft: a `./` ref names nothing yet. */
    expect(pictureFor("./close-up.mp4", null)).toBe("");
  });
});

describe("mediaKind", () => {
  it("calls a template entry an image: a render is a picture", () => {
    expect(mediaKind({ template: "flat-lay-01", colour: "black" })).toBe("image");
  });

  it("calls a file ref a video by its extension, in any case", () => {
    expect(mediaKind("common-media/intro.mp4")).toBe("video");
    expect(mediaKind("./IMG_1234.MOV")).toBe("video");
  });

  it("calls every other file ref an image", () => {
    expect(mediaKind("common-media/sizing.png")).toBe("image");
    expect(mediaKind("./shots/back.JPEG")).toBe("image");
  });
});

describe("templatePicture", () => {
  it("answers for a template the locator is offering but the listing has not taken", () => {
    expect(templatePicture("flat-lay-01", "moss", null)).toBe(
      "/api/templates/flat-lay-01/photo?colour=moss",
    );
  });

  it("agrees with pictureFor for the same template and colour", () => {
    expect(templatePicture("flat-lay-01", "black", "take-a-hike")).toBe(
      pictureFor({ template: "flat-lay-01", colour: "black" }, "take-a-hike"),
    );
  });
});

describe("scenePath", () => {
  it("reports the file the server resolved, not one derived from the convention", () => {
    const prefixed: TemplateSummary = {
      ...FLAT_LAY,
      photos: [{ colour: "black", file: "mockup-templates/flat-lay-01/flat-lay-01-black.png" }],
    };
    expect(scenePath(prefixed, "flat-lay-01", "black")).toBe(
      "mockup-templates/flat-lay-01/flat-lay-01-black.png",
    );
  });

  it("uses the served path for an ordinary colour-matrix photo", () => {
    expect(scenePath(FLAT_LAY, "flat-lay-01", "ivory")).toBe(
      "mockup-templates/flat-lay-01/ivory.png",
    );
  });

  it("names the file the template would need for a colour it has no photo for", () => {
    expect(scenePath(FLAT_LAY, "flat-lay-01", "moss")).toBe(
      "mockup-templates/flat-lay-01/moss.png",
    );
  });

  it("falls back to the convention for a template the client has not loaded", () => {
    expect(scenePath(undefined, "flat-lay-01", "black")).toBe(
      "mockup-templates/flat-lay-01/black.png",
    );
  });

  it("names scene.png for a fixed-scene template (PRD 28)", () => {
    expect(scenePath(undefined, "rack-shot", null)).toBe("mockup-templates/rack-shot/scene.png");
  });
});
