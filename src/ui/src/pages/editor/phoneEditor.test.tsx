import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ActionLink } from "../../components/ActionLink";
import { PHONE_QUERY } from "../../phone/usePhone";
import type { Issue, MediaEntry } from "../../types";
import { HeadAlert } from "./HeadAlert";
import { HeadAlertSlot } from "./headAlertSlot";
import { HeadMore } from "./HeadMore";
import { IssuesBanner } from "./IssuesBanner";
import { MediaReel } from "./MediaReel";

/**
 * The editor's phone-only branches. jsdom has no `matchMedia`, so every
 * other test sees the desktop editor; here the phone query matches.
 */

beforeEach(() => {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query === PHONE_QUERY,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const MEDIA: MediaEntry[] = [
  { template: "flat-lay-01", colour: "black" },
  { template: "flat-lay-01", colour: "ivory" },
  { template: "fence-01", colour: "black" },
];

function reel(selectedIndex: number | null) {
  const props = {
    media: MEDIA,
    scene: null,
    swatchTemplate: null,
    selectedIndex,
    listing: "take-a-hike",
    files: [],
    onRemove: vi.fn(),
    onReorder: vi.fn(),
    onFocus: vi.fn(),
    onAdd: vi.fn(),
  };
  render(<MediaReel {...props} />);
  return props;
}

describe("the phone reel", () => {
  it("says a tap moves a tile, and offers Add media", () => {
    const props = reel(null);
    expect(screen.getByText("Tap an image to move or remove it")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add media" }));
    expect(props.onAdd).toHaveBeenCalled();
    expect(screen.queryByRole("group", { name: /^Move / })).not.toBeInTheDocument();
  });

  it("moves the selected tile one place, or to the front", () => {
    const props = reel(1);
    const bar = screen.getByRole("group", { name: "Move flat-lay-01 · ivory" });
    fireEvent.click(within(bar).getByRole("button", { name: "Move later" }));
    expect(props.onReorder).toHaveBeenLastCalledWith(1, 2);
    fireEvent.click(within(bar).getByRole("button", { name: "Move earlier" }));
    expect(props.onReorder).toHaveBeenLastCalledWith(1, 0);
    fireEvent.click(within(bar).getByRole("button", { name: "Make thumbnail" }));
    expect(props.onReorder).toHaveBeenLastCalledWith(1, 0);
    fireEvent.click(within(bar).getByRole("button", { name: "Remove flat-lay-01 · ivory" }));
    expect(props.onRemove).toHaveBeenCalledWith(1);
  });

  it("cannot move the first tile earlier or make it the thumbnail again", () => {
    reel(0);
    const bar = screen.getByRole("group", { name: /^Move / });
    expect(within(bar).getByRole("button", { name: "Move earlier" })).toBeDisabled();
    expect(within(bar).getByRole("button", { name: "Make thumbnail" })).toBeDisabled();
    expect(within(bar).getByRole("button", { name: "Move later" })).toBeEnabled();
  });
});

describe("the phone reel's selected tile", () => {
  function selected(media: MediaEntry[], index: number) {
    const props = {
      media,
      scene: null,
      swatchTemplate: null,
      selectedIndex: index,
      listing: "take-a-hike",
      files: [],
      onRemove: vi.fn(),
      onReorder: vi.fn(),
      onFocus: vi.fn(),
      onView: vi.fn(),
      onDeselect: vi.fn(),
    };
    const { container } = render(<MediaReel {...props} />);
    const faces = container.querySelectorAll(".rtile__face");
    return { props, faces };
  }

  it("opens full size from its bar", () => {
    const { props } = selected(MEDIA, 2);
    const bar = screen.getByRole("group", { name: "Move fence-01 · black" });
    fireEvent.click(within(bar).getByRole("button", { name: "View" }));
    expect(props.onView).toHaveBeenCalledWith(2);
  });

  it("lets go on the bar's Done, a second tap or Escape", () => {
    const { props, faces } = selected(MEDIA, 2);
    const bar = screen.getByRole("group", { name: "Move fence-01 · black" });
    fireEvent.click(within(bar).getByRole("button", { name: "Done" }));
    expect(props.onDeselect).toHaveBeenCalledTimes(1);

    fireEvent.click(faces[2] as Element);
    expect(props.onDeselect).toHaveBeenCalledTimes(2);
    expect(props.onFocus).not.toHaveBeenCalled();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(props.onDeselect).toHaveBeenCalledTimes(3);
  });

  it("calls a video a video, and says why it cannot move", () => {
    selected(["./front.png", "./spin.mp4", "./back.png"], 1);
    const bar = screen.getByRole("group", { name: /^Move .*spin/ });
    expect(bar).toHaveTextContent("Video 2:");
    expect(bar).toHaveTextContent("Etsy shows a listing’s video second");
    expect(within(bar).getByRole("button", { name: "Move later" })).toBeDisabled();
  });

  it("says nothing about staying put for an image that can move", () => {
    selected(MEDIA, 1);
    const bar = screen.getByRole("group", { name: /^Move / });
    expect(bar).toHaveTextContent("Image 2:");
    expect(bar).not.toHaveTextContent("stays in that place");
  });
});

const ISSUES: Issue[] = [
  { severity: "block", tab: "pricing", where: "Pricing", message: "No pricing plan" },
  { severity: "warn", tab: "details", where: "Listing Details › Tags", message: "No tags" },
] as Issue[];

describe("the phone issues banner", () => {
  it("starts folded to its summary and unfolds on Show", () => {
    render(<IssuesBanner issues={ISSUES} activeTab="variants" onJumpTo={vi.fn()} />);
    expect(screen.getByText(/1 to fix before deploying/)).toBeInTheDocument();
    expect(screen.queryByText("No pricing plan")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(screen.getByText("No pricing plan")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hide" }));
    expect(screen.queryByText("No pricing plan")).not.toBeInTheDocument();
  });

  it("folds again on a Fix, on its way to the tab", () => {
    const jump = vi.fn();
    render(<IssuesBanner issues={ISSUES} activeTab="variants" onJumpTo={jump} />);
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    fireEvent.click(screen.getByRole("button", { name: "Fix: No tags" }));
    expect(jump).toHaveBeenCalledWith("details");
    expect(screen.queryByText("No pricing plan")).not.toBeInTheDocument();
  });
});

describe("an action's error", () => {
  it("shows under the phone head rather than in the closed sheet", () => {
    const slot = document.createElement("div");
    document.body.append(slot);
    render(
      <HeadAlertSlot value={slot}>
        <div data-testid="sheet">
          <HeadAlert>Could not delete x</HeadAlert>
        </div>
      </HeadAlertSlot>,
    );
    expect(slot).toHaveTextContent("Could not delete x");
    expect(screen.getByTestId("sheet")).toBeEmptyDOMElement();
    slot.remove();
  });

  it("stays beside its action without a slot", () => {
    render(
      <div data-testid="row">
        <HeadAlert>Could not delete x</HeadAlert>
      </div>,
    );
    expect(screen.getByTestId("row")).toHaveTextContent("Could not delete x");
    expect(screen.getByRole("alert")).toHaveClass("action-row__error");
  });
});

describe("the phone head's overflow", () => {
  it("opens the actions in a sheet, which closes once one is picked", () => {
    const retire = vi.fn();
    render(
      <HeadMore title="take-a-hike">
        <ActionLink icon={null} onClick={retire}>
          Retire
        </ActionLink>
      </HeadMore>,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    const sheet = screen.getByRole("dialog", { name: "take-a-hike" });
    fireEvent.click(within(sheet).getByRole("button", { name: "Retire" }));
    expect(retire).toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes on Done", () => {
    render(
      <HeadMore title="take-a-hike">
        <span>nothing</span>
      </HeadMore>,
    );
    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    const sheet = screen.getByRole("dialog");
    fireEvent.click(within(sheet).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
