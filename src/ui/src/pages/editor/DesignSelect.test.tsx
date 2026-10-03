import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../../api/calibrator";
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

describe("DesignSelect previewing a listing template", () => {
  /* UI doc §3: the row picks a *preview* design -- the calibrator's test
     designs plus recent workspace designs -- which only changes how the
     previews look and is never saved. */
  const TEST_DESIGNS = [
    { id: "bundled-grid", label: "Grid / ruler target", source: "bundled" as const },
    { id: "bundled-on-light", label: "Sample art · light ink", source: "bundled" as const },
    { id: "my-art", label: "my-art", source: "upload" as const },
  ];

  beforeEach(() => {
    vi.spyOn(calibrator, "listDesigns").mockResolvedValue(TEST_DESIGNS);
  });

  it("says it is only a preview, and names the test design", async () => {
    render(<DesignSelect preview={{ kind: "test", id: "bundled-grid" }} onPreview={vi.fn()} />);

    expect(await screen.findByText("Preview design: Grid / ruler target")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Only for previewing this template — each listing in a batch gets its own design",
      ),
    ).toBeInTheDocument();
  });

  it("offers test designs and recent designs, and picks either", async () => {
    const onPreview = vi.fn();
    render(<DesignSelect preview={{ kind: "test", id: "bundled-grid" }} onPreview={onPreview} />);

    fireEvent.click(await screen.findByRole("button", { name: "Change preview design" }));
    expect(screen.getByText("Preview designs")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Grid \/ ruler target/ })).toHaveClass(
      "template-card--active",
    );
    fireEvent.click(await screen.findByRole("button", { name: /wildflower-botanical/ }));
    fireEvent.click(screen.getByRole("button", { name: "Change preview design" }));
    fireEvent.click(screen.getByRole("button", { name: /my-art/ }));

    expect(onPreview.mock.calls).toEqual([
      [{ kind: "design", name: "wildflower-botanical", file: "designs/wildflower-botanical.png" }],
      [{ kind: "test", id: "my-art" }],
    ]);
  });

  it("uploads a PNG to preview with, as the calibrator does", async () => {
    const upload = vi
      .spyOn(calibrator, "uploadDesign")
      .mockResolvedValue({ id: "fresh", label: "fresh", source: "upload" });
    const onPreview = vi.fn();
    render(<DesignSelect preview={{ kind: "test", id: "bundled-grid" }} onPreview={onPreview} />);

    fireEvent.click(await screen.findByRole("button", { name: "Change preview design" }));
    const file = new File(["png"], "fresh.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Upload a PNG to preview…"), {
      target: { files: [file] },
    });

    await vi.waitFor(() => expect(onPreview).toHaveBeenCalledWith({ kind: "test", id: "fresh" }));
    expect(upload).toHaveBeenCalledWith(file);
  });
});
