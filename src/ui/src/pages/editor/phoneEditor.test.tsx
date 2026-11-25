import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ActionLink } from "../../components/ActionLink";
import { PHONE_QUERY } from "../../phone/usePhone";
import type { Issue, MediaEntry } from "../../types";
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
