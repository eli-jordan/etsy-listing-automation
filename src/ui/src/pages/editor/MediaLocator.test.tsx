import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MediaOwner } from "../../media";
import type { ListingDetail, MediaFileSummary, TemplateSummary } from "../../types";
import { MediaLocator } from "./MediaLocator";

/**
 * The locator's *Files* mode: one list, grouped by the two roots a
 * file ref can name -- *This listing ·./* and *Shared · common-media/* --
 * with images and videos mixed, and a video drawn by the browser from its own
 * first frame.
 */

const BACK: MediaFileSummary = {
  name: "shots/back.png",
  file: "listings/take-a-hike/shots/back.png",
  ref: "./shots/back.png",
  kind: "image",
};
const CLOSE_UP: MediaFileSummary = {
  name: "close-up.mp4",
  file: "listings/take-a-hike/close-up.mp4",
  ref: "./close-up.mp4",
  kind: "video",
};
const SIZING: MediaFileSummary = {
  name: "size-guide.png",
  file: "common-media/size-guide.png",
  ref: "common-media/size-guide.png",
  kind: "image",
};
const GUIDE: MediaFileSummary = {
  name: "videos/size-guide.mp4",
  file: "common-media/videos/size-guide.mp4",
  ref: "common-media/videos/size-guide.mp4",
  kind: "video",
};

function locator(
  over: {
    media?: ListingDetail["media"];
    local?: MediaFileSummary[] | null;
    shared?: MediaFileSummary[];
    owner?: MediaOwner | null;
  } = {},
) {
  const onToggleFile = vi.fn();
  const onFocus = vi.fn();
  const detail = {
    name: "take-a-hike",
    media: over.media ?? [],
    colors: ["black"],
    etsy: { variation_images: null },
  } as unknown as ListingDetail;
  render(
    <MediaLocator
      detail={detail}
      templates={[]}
      local={over.local === undefined ? [BACK, CLOSE_UP] : over.local}
      shared={over.shared ?? [SIZING, GUIDE]}
      onToggleTemplate={vi.fn()}
      onToggleFile={onToggleFile}
      onAddMissingColours={vi.fn()}
      onToggleSwatchSource={vi.fn()}
      onFocus={onFocus}
      {...(over.owner === undefined ? {} : { owner: over.owner })}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Files" }));
  return { onToggleFile, onFocus };
}

function group(label: RegExp): HTMLElement {
  return screen.getByRole("group", { name: label });
}

function template(over: Partial<TemplateSummary> & { name: string }): TemplateSummary {
  return {
    kind: "single",
    colours: [],
    photos: [],
    has_config: true,
    labels: [],
    status: "calibrated",
    status_reason: null,
    width: 480,
    height: 576,
    ...over,
  };
}

/** The Mockup templates half, as a listing named by `scope` would open it. */
function templatesLocator(templates: TemplateSummary[], scope: string | null = null) {
  const detail = {
    name: "take-a-hike",
    media: [],
    colors: ["black"],
    etsy: { variation_images: null },
  } as unknown as ListingDetail;
  return render(
    <MediaLocator
      detail={detail}
      templates={templates}
      local={[BACK]}
      shared={[SIZING]}
      onToggleTemplate={vi.fn()}
      onToggleFile={vi.fn()}
      onAddMissingColours={vi.fn()}
      onToggleSwatchSource={vi.fn()}
      onFocus={vi.fn()}
      scope={scope}
    />,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

describe("MediaLocator's template rows", () => {
  it("shows a template's labels in place of its kind", () => {
    templatesLocator([template({ name: "tree", labels: ["theme:christmas", "shot:flat lay"] })]);

    expect(screen.getByText("theme:christmas · shot:flat lay")).toBeInTheDocument();
    expect(screen.queryByText(/one fixed photo/)).not.toBeInTheDocument();
  });

  it("says when a template has no labels", () => {
    templatesLocator([template({ name: "tree" })]);

    expect(screen.getByText("No labels")).toBeInTheDocument();
  });
});

const box = () => screen.getByRole("combobox", { name: /Search templates/ });

function typeInBox(text: string) {
  fireEvent.change(box(), { target: { value: text } });
}

function pickLabel(label: string) {
  fireEvent.click(box());
  fireEvent.click(screen.getByRole("option", { name: new RegExp(`^${label}`) }));
}

function shownTemplates(): (string | null)[] {
  return [...document.querySelectorAll(".loc-tmpl__name")].map((name) => name.textContent);
}

describe("MediaLocator's template search", () => {
  const tree = template({ name: "woman-by-tree", labels: ["theme:christmas"] });
  const fire = template({ name: "fireplace", labels: ["theme:christmas", "shot:flat lay"] });
  const beach = template({ name: "beach-tree", labels: ["theme:summer"] });

  it("opens on every template, with the filter empty", () => {
    templatesLocator([tree, fire, beach]);

    expect(screen.getByRole("status")).toHaveTextContent("3 of 3 templates");
    expect(shownTemplates()).toEqual(["woman-by-tree", "fireplace", "beach-tree"]);
  });

  it("lists only what holds every pill, and says how many that leaves", () => {
    templatesLocator([tree, fire, beach]);

    pickLabel("theme:christmas");
    expect(shownTemplates()).toEqual(["woman-by-tree", "fireplace"]);
    expect(screen.getByRole("status")).toHaveTextContent("2 of 3 templates");

    pickLabel("shot:flat lay");
    expect(shownTemplates()).toEqual(["fireplace"]);
    expect(screen.getByRole("status")).toHaveTextContent("1 of 3 templates");
  });

  it("narrows what the pills leave by title, not every template", () => {
    templatesLocator([tree, fire, beach]);

    pickLabel("theme:christmas");
    typeInBox(" TREE ");

    expect(shownTemplates()).toEqual(["woman-by-tree"]);
    expect(screen.getByRole("status")).toHaveTextContent("1 of 3 templates");
  });

  it("does not search labels with plain text", () => {
    templatesLocator([tree, beach]);

    typeInBox("christmas");

    expect(shownTemplates()).toEqual([]);
    expect(screen.getByText("No template matches.")).toBeInTheDocument();
  });

  it("counts only the calibrated templates it lists", () => {
    const draft = template({
      name: "uncalibrated",
      labels: ["theme:christmas", "theme:easter"],
      status: "needs-calibration",
    });
    templatesLocator([tree, fire, beach, draft]);

    expect(screen.getByRole("status")).toHaveTextContent("3 of 3 templates");

    fireEvent.click(box());
    expect(screen.getByRole("option", { name: /^theme:christmas/ })).toHaveTextContent(/2$/);
    expect(screen.queryByRole("option", { name: /theme:easter/ })).not.toBeInTheDocument();
  });

  it("reads right with one template", () => {
    templatesLocator([tree]);

    expect(screen.getByRole("status")).toHaveTextContent(/^1 of 1 template$/);
  });
});

describe("MediaLocator's label pills in view memory", () => {
  const SCOPE = "listing:take-a-hike";
  const tree = template({ name: "woman-by-tree", labels: ["theme:christmas"] });
  const beach = template({ name: "beach", labels: ["theme:summer"] });

  it("keeps the pills through a remount, as a move to Pricing and back causes", () => {
    const first = templatesLocator([tree, beach], SCOPE);
    pickLabel("theme:christmas");
    first.unmount();

    templatesLocator([tree, beach], SCOPE);

    expect(screen.getByRole("button", { name: "Remove theme:christmas" })).toBeInTheDocument();
    expect(shownTemplates()).toEqual(["woman-by-tree"]);
    expect(screen.getByRole("status")).toHaveTextContent("1 of 2 templates");
  });

  it("keeps a removed pill removed", () => {
    const first = templatesLocator([tree, beach], SCOPE);
    pickLabel("theme:christmas");
    fireEvent.click(screen.getByRole("button", { name: "Remove theme:christmas" }));
    first.unmount();

    templatesLocator([tree, beach], SCOPE);

    expect(shownTemplates()).toEqual(["woman-by-tree", "beach"]);
  });

  it("keeps each listing's pills apart", () => {
    const first = templatesLocator([tree, beach], SCOPE);
    pickLabel("theme:christmas");
    first.unmount();

    const second = templatesLocator([tree, beach], "listing:santa-cookie-crew");
    expect(screen.queryByRole("button", { name: /^Remove / })).not.toBeInTheDocument();
    pickLabel("theme:summer");
    second.unmount();

    templatesLocator([tree, beach], SCOPE);
    expect(screen.getByRole("button", { name: "Remove theme:christmas" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove theme:summer" })).not.toBeInTheDocument();
  });

  it("keeps a listing's pills apart from a listing template of the same name", () => {
    const first = templatesLocator([tree, beach], SCOPE);
    pickLabel("theme:christmas");
    first.unmount();

    templatesLocator([tree, beach], "listing-template:take-a-hike");

    expect(screen.queryByRole("button", { name: /^Remove / })).not.toBeInTheDocument();
  });

  it.each([
    ["a string", '"theme:christmas"'],
    ["a list holding something else", '["theme:christmas", 3]'],
    ["an object", '{"on": ["theme:christmas"]}'],
    ["null", "null"],
    ["text that is not JSON", "theme:christmas"],
  ])("ignores %s left by an older build", (_name, stored) => {
    sessionStorage.setItem(`editor-view:${SCOPE}:locator-labels`, stored);

    templatesLocator([tree, beach], SCOPE);

    expect(screen.queryByRole("button", { name: /^Remove / })).not.toBeInTheDocument();
    expect(shownTemplates()).toEqual(["woman-by-tree", "beach"]);
  });

  it("keeps a pill no template holds any more, so the seller can see why the list is empty", () => {
    const first = templatesLocator([tree, beach], SCOPE);
    pickLabel("theme:christmas");
    first.unmount();

    templatesLocator([beach], SCOPE);

    expect(screen.getByRole("button", { name: "Remove theme:christmas" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("0 of 1 template");
    expect(screen.getByText("No template matches.")).toBeInTheDocument();
  });
});

describe("MediaLocator's switch to Files", () => {
  const tree = template({ name: "woman-by-tree", labels: ["theme:christmas"] });
  const beach = template({ name: "beach", labels: ["theme:summer"] });
  const files = () => screen.getByRole("button", { name: "Files" });
  const mockups = () => screen.getByRole("button", { name: "Mockup templates" });

  it("keeps the pills and clears the text", () => {
    templatesLocator([tree, beach]);
    pickLabel("theme:christmas");
    typeInBox("tree");

    fireEvent.click(files());
    fireEvent.click(mockups());

    expect(screen.getByRole("button", { name: "Remove theme:christmas" })).toBeInTheDocument();
    expect(box()).toHaveValue("");
    expect(shownTemplates()).toEqual(["woman-by-tree"]);
  });

  it("does not carry a file search back to the templates", () => {
    templatesLocator([tree, beach]);
    fireEvent.click(files());
    fireEvent.change(screen.getByPlaceholderText("Search files…"), { target: { value: "back" } });

    fireEvent.click(mockups());

    expect(box()).toHaveValue("");
    expect(shownTemplates()).toEqual(["woman-by-tree", "beach"]);
  });

  it("gives Files its plain search, with no pills, labels or result line", () => {
    templatesLocator([tree, beach]);
    pickLabel("theme:christmas");

    fireEvent.click(files());

    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Remove / })).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "shots/back.png" })).toBeInTheDocument();
  });

  it("comes back to Files with the pills still waiting after a remount", () => {
    const scope = "listing:take-a-hike";
    const first = templatesLocator([tree, beach], scope);
    pickLabel("theme:christmas");
    fireEvent.click(files());
    first.unmount();

    templatesLocator([tree, beach], scope);
    expect(screen.getByPlaceholderText("Search files…")).toBeInTheDocument();

    fireEvent.click(mockups());
    expect(shownTemplates()).toEqual(["woman-by-tree"]);
  });
});

describe("MediaLocator's file list", () => {
  it("groups the listing's own files before the shared ones without exposing ref roots", () => {
    locator();

    const groups = screen.getAllByRole("group");
    expect(groups.map((g) => g.getAttribute("aria-label"))).toEqual(["This listing", "Shared"]);
    expect(within(group(/This listing/)).getByText("shots/back.png")).toBeInTheDocument();
    expect(within(group(/This listing/)).getByText("close-up.mp4")).toBeInTheDocument();
    expect(within(group(/Shared/)).getByText("size-guide.png")).toBeInTheDocument();
    expect(within(group(/Shared/)).getByText("videos/size-guide.mp4")).toBeInTheDocument();
  });

  it("calls a listing template's own files This template, drawn from its directory", () => {
    /* UI doc, *Existing components the template editor needs*. */
    const asset = { ...BACK, ref: "./assets/shots/back.png", name: "assets/shots/back.png" };
    locator({ local: [asset], owner: { kind: "listing-template", name: "tee" } });

    expect(screen.getAllByRole("group").map((g) => g.getAttribute("aria-label"))).toEqual([
      "This template",
      "Shared",
    ]);
    expect(group(/This template/).querySelector("img")).toHaveAttribute(
      "src",
      "/api/listing-templates/tee/media-files/assets/shots/back.png/thumbnail",
    );
  });

  it("adds a file as the ref it is stored under, whichever group it is in", () => {
    const { onToggleFile } = locator();

    fireEvent.click(screen.getByRole("button", { name: "close-up.mp4" }));
    fireEvent.click(screen.getByRole("button", { name: "size-guide.png" }));

    expect(onToggleFile.mock.calls).toEqual([["./close-up.mp4"], ["common-media/size-guide.png"]]);
  });

  it("marks what is already in the listing", () => {
    locator({ media: ["common-media/size-guide.png"] });

    expect(screen.getByRole("button", { name: "size-guide.png" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "shots/back.png" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("points the preview at a file on hover", () => {
    const { onFocus } = locator();

    fireEvent.mouseEnter(screen.getByRole("button", { name: "shots/back.png" }));

    expect(onFocus).toHaveBeenCalledWith({ kind: "file", asset: BACK });
  });

  it("draws an image from its thumbnail, under the directory it lives in", () => {
    locator();

    const back = screen.getByRole("button", { name: "shots/back.png" });
    expect(back.querySelector("img")).toHaveAttribute(
      "src",
      "/api/listings/take-a-hike/media-files/shots/back.png/thumbnail",
    );
    const sizing = screen.getByRole("button", { name: "size-guide.png" });
    expect(sizing.querySelector("img")).toHaveAttribute(
      "src",
      "/api/common-media/size-guide.png/thumbnail",
    );
  });

  it("searches both groups by name", () => {
    locator();

    fireEvent.change(screen.getByPlaceholderText("Search files…"), {
      target: { value: "size" },
    });

    expect(screen.queryByText("shots/back.png")).not.toBeInTheDocument();
    expect(screen.getByText("size-guide.png")).toBeInTheDocument();
    expect(screen.getByText("videos/size-guide.mp4")).toBeInTheDocument();
  });

  it("says so when a search matches nothing in either group", () => {
    locator();

    fireEvent.change(screen.getByPlaceholderText("Search files…"), {
      target: { value: "zzz" },
    });

    expect(screen.getByText("No file matches that search.")).toBeInTheDocument();
  });

  it("omits empty groups instead of showing file-system instructions", () => {
    locator({ local: [], shared: [] });

    expect(document.querySelectorAll(".loc-group")).toHaveLength(0);
  });

  it("has no This listing group for a draft, which has no directory yet", () => {
    locator({ local: null });

    expect(screen.queryByRole("group", { name: /This listing/ })).not.toBeInTheDocument();
    expect(group(/Shared/)).toBeInTheDocument();
  });
});

describe("MediaLocator's video rows", () => {
  function video(name: string): HTMLVideoElement {
    const row = screen.getByRole("button", { name });
    const element = row.querySelector("video");
    expect(element).not.toBeNull();
    return element as HTMLVideoElement;
  }

  it("draws a video's first frame with a muted, metadata-only <video>", () => {
    locator();

    const clip = video("close-up.mp4");
    expect(clip).toHaveAttribute(
      "src",
      "/api/listings/take-a-hike/media-files/close-up.mp4/file#t=0.5",
    );
    expect(clip).toHaveAttribute("preload", "metadata");
    expect(clip.muted).toBe(true);
    expect(screen.getByRole("button", { name: "close-up.mp4" }).querySelector("img")).toBeNull();
  });

  it("shows the clip's length once the browser has read it", () => {
    locator();
    const clip = video("videos/size-guide.mp4");
    const row = screen.getByRole("button", { name: "videos/size-guide.mp4" });
    expect(within(row).getByText("▶")).toBeInTheDocument();

    Object.defineProperty(clip, "duration", { value: 6.2, configurable: true });
    fireEvent.loadedMetadata(clip);

    expect(within(row).getByText("▶ 0:06")).toBeInTheDocument();
  });

  it("formats a clip past a minute in minutes and seconds", () => {
    locator();
    const clip = video("close-up.mp4");

    Object.defineProperty(clip, "duration", { value: 75, configurable: true });
    fireEvent.loadedMetadata(clip);

    expect(screen.getByText("▶ 1:15")).toBeInTheDocument();
  });

  it("plays muted from the start on hover, and goes back to its poster frame after", () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    const pause = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
    locator();
    const clip = video("close-up.mp4");
    const row = screen.getByRole("button", { name: "close-up.mp4" });

    fireEvent.mouseEnter(row);
    expect(play).toHaveBeenCalledTimes(1);
    expect(clip.currentTime).toBe(0);

    fireEvent.mouseLeave(row);
    expect(pause).toHaveBeenCalledTimes(1);
    expect(clip.currentTime).toBe(0.5);
  });

  it("survives a browser that refuses to play", () => {
    vi.spyOn(HTMLMediaElement.prototype, "play").mockRejectedValue(new Error("NotAllowedError"));
    locator();

    expect(() =>
      fireEvent.mouseEnter(screen.getByRole("button", { name: "close-up.mp4" })),
    ).not.toThrow();
  });

  it("disables and explains an unselected third clip without trapping selected clips", () => {
    const { onToggleFile } = locator({
      media: ["a.png", CLOSE_UP.ref, "b.png", "./second.mp4"],
    });
    const selected = screen.getByRole("button", { name: "close-up.mp4" });
    const third = screen.getByRole("button", { name: "videos/size-guide.mp4" });
    const explanation = screen.getByText(
      "2-video limit reached — remove one before adding another.",
    );

    expect(explanation).toBeVisible();
    expect(selected).toBeEnabled();
    fireEvent.click(selected);
    expect(onToggleFile).toHaveBeenCalledWith(CLOSE_UP.ref);

    expect(third).toBeDisabled();
    expect(third).toHaveAttribute("aria-describedby", explanation.id);
    expect(third).toHaveAttribute("title", "Etsy allows at most 2 videos per listing");
    fireEvent.click(third);
    expect(onToggleFile).toHaveBeenCalledTimes(1);
  });
});
