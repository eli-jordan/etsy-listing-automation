import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as listingsApi from "../../api/listings";
import { DesignSelect } from "./DesignSelect";

const DESIGNS = [
  { name: "take-a-hike", file: "designs/take-a-hike.png" },
  { name: "wildflower-botanical", file: "designs/wildflower-botanical.png" },
  { name: "cosmic-cat", file: "designs/cosmic-cat.png" },
  { name: "desert-bloom", file: "designs/desert-bloom.png" },
  { name: "trail-map-badge", file: "designs/trail-map-badge.png" },
];

beforeEach(() => {
  vi.spyOn(listingsApi, "listListingDesigns").mockResolvedValue(DESIGNS);
});

afterEach(() => vi.restoreAllMocks());

describe("DesignSelect", () => {
  it("names the artwork the listing prints, and the file it comes from", async () => {
    render(<DesignSelect design={{ default: "designs/take-a-hike.png" }} onPick={vi.fn()} />);

    expect(await screen.findByText("take-a-hike")).toBeInTheDocument();
    expect(screen.getByText("designs/take-a-hike.png")).toBeInTheDocument();
  });

  it("says so when no design is set, since nothing can be printed without one", async () => {
    render(<DesignSelect design={{}} onPick={vi.fn()} />);
    expect(await screen.findByText("No design selected")).toBeInTheDocument();
  });

  it("picks a design from the recent list and writes a workspace-rooted ref", async () => {
    /* PRD 72: no prefix is the workspace root -- the same ref `new` writes. */
    const onPick = vi.fn();
    render(<DesignSelect design={{ default: "designs/take-a-hike.png" }} onPick={onPick} />);

    fireEvent.click(await screen.findByRole("button", { name: /Change design/ }));
    fireEvent.click(screen.getByRole("button", { name: /wildflower-botanical/ }));

    expect(onPick).toHaveBeenCalledWith("designs/wildflower-botanical.png");
  });

  it("searches the whole library when the recent four are not enough", async () => {
    const onPick = vi.fn();
    render(<DesignSelect design={{}} onPick={onPick} />);

    fireEvent.click(await screen.findByRole("button", { name: /Change design/ }));
    expect(screen.queryByRole("button", { name: /trail-map-badge/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Find a design…" }));
    fireEvent.change(screen.getByPlaceholderText("Search designs…"), {
      target: { value: "trail" },
    });

    fireEvent.click(screen.getByRole("button", { name: /trail-map-badge/ }));
    expect(onPick).toHaveBeenCalledWith("designs/trail-map-badge.png");
  });

  it("reports an empty search rather than an empty list", async () => {
    render(<DesignSelect design={{}} onPick={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Change design/ }));
    fireEvent.click(screen.getByRole("button", { name: "Find a design…" }));
    fireEvent.change(screen.getByPlaceholderText("Search designs…"), {
      target: { value: "zzz" },
    });

    expect(screen.getByText("No designs match your search")).toBeInTheDocument();
  });

  it("will not edit a multi-artwork listing, which has no single design to swap", async () => {
    /* `design:` keyed on-light/on-dark is resolved per colour and garment by
       the render stage; picking "the" design here would silently drop one. */
    render(
      <DesignSelect
        design={{
          "on-light": "designs/take-a-hike-light.png",
          "on-dark": "designs/take-a-hike-dark.png",
        }}
        onPick={vi.fn()}
      />,
    );

    expect(await screen.findByText("2 artworks")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Change design/ })).not.toBeInTheDocument();
  });
});
