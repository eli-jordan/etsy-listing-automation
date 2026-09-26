import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ListingDetail, MediaFileSummary } from "../../types";
import { MediaLocator } from "./MediaLocator";

/**
 * The locator's *Files* mode (PRD 72): one list, grouped by the two roots a
 * file ref can name -- *This listing · ./* and *Shared · common-media/* --
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
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Files" }));
  return { onToggleFile, onFocus };
}

function group(label: RegExp): HTMLElement {
  return screen.getByRole("group", { name: label });
}

afterEach(() => vi.restoreAllMocks());

describe("MediaLocator's file list", () => {
  it("groups the listing's own files before the shared ones, each under its root", () => {
    locator();

    const groups = screen.getAllByRole("group");
    expect(groups.map((g) => g.getAttribute("aria-label"))).toEqual([
      "This listing · ./",
      "Shared · common-media/",
    ]);
    expect(within(group(/This listing/)).getByText("shots/back.png")).toBeInTheDocument();
    expect(within(group(/This listing/)).getByText("close-up.mp4")).toBeInTheDocument();
    expect(within(group(/Shared/)).getByText("size-guide.png")).toBeInTheDocument();
    expect(within(group(/Shared/)).getByText("videos/size-guide.mp4")).toBeInTheDocument();
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

  it("says where to put files when a group has none", () => {
    locator({ local: [], shared: [] });

    expect(
      within(group(/This listing/)).getByText(/Nothing in listings\/take-a-hike\//),
    ).toBeInTheDocument();
    expect(within(group(/Shared/)).getByText(/Nothing in common-media\//)).toBeInTheDocument();
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
