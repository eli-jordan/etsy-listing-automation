import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../api/calibrator";
import type { ColourReportRow } from "../types";
import { KindPicker } from "./KindPicker";

const CLEAN: ColourReportRow[] = [
  { filename: "sand.png", colour: "sand", clean: true },
  { filename: "black.png", colour: "black", clean: true },
];

const MESSY: ColourReportRow[] = [
  ...CLEAN,
  { filename: "Heather Grey.png", colour: "heather-grey", clean: false },
];

afterEach(() => vi.restoreAllMocks());
beforeEach(() => {
  vi.spyOn(calibrator, "getColourReport").mockResolvedValue(CLEAN);
});

function renderPicker(over: Partial<Parameters<typeof KindPicker>[0]> = {}) {
  const onAssigned = vi.fn();
  render(<KindPicker templateName="boxy-tee" onAssigned={onAssigned} {...over} />);
  return { onAssigned };
}

const ONE_PHOTO: ColourReportRow[] = [{ filename: "photo.png", colour: "photo", clean: true }];

describe("the default kind follows the photo count", () => {
  it("defaults to colour matrix when there are several photos", async () => {
    renderPicker();
    await waitFor(() =>
      expect(screen.getByRole("radio", { name: /Colour Matrix/ })).toBeChecked(),
    );
  });

  it("defaults to single, and disables colour matrix, for one photo", async () => {
    /* "One photo per colour" over a single file is a matrix of one -- which is
     * what `single` already is. Worse, accepting it names the colour after the
     * filename, so `photo.png` became a garment colour called "photo". */
    vi.spyOn(calibrator, "getColourReport").mockResolvedValue(ONE_PHOTO);
    renderPicker();

    await waitFor(() => expect(screen.getByRole("radio", { name: /Single/ })).toBeChecked());
    expect(screen.getByRole("radio", { name: /Colour Matrix/ })).toBeDisabled();
    expect(screen.getByText("needs more than one photo")).toBeInTheDocument();
  });

  it("multiple stays available for one photo", async () => {
    // A chart is one photo with several garments in it -- exactly the
    // single-photo case, so this must not be disabled alongside colour matrix.
    vi.spyOn(calibrator, "getColourReport").mockResolvedValue(ONE_PHOTO);
    renderPicker();
    await waitFor(() => expect(screen.getByRole("radio", { name: /Single/ })).toBeChecked());
    expect(screen.getByRole("radio", { name: /Multiple/ })).toBeEnabled();
  });

  it("assigns single for a one-photo template without anyone touching a radio", async () => {
    vi.spyOn(calibrator, "getColourReport").mockResolvedValue(ONE_PHOTO);
    const assignSpy = vi.spyOn(calibrator, "assignKind").mockResolvedValue({
      kind: "single",
      colour: null,
      artwork: null,
      bounding_box: [
        { x: 0, y: 0 },
        { x: 1, y: 0 },
        { x: 1, y: 1 },
        { x: 0, y: 1 },
      ],
      displace: { enabled: false, strength: 0 },
      shade: { enabled: true, opacity: 0.6, blend: "soft-light" },
    });
    renderPicker();
    await waitFor(() => expect(screen.getByRole("radio", { name: /Single/ })).toBeChecked());

    fireEvent.click(screen.getByRole("button", { name: /Start calibrating/ }));
    await waitFor(() => expect(assignSpy).toHaveBeenCalledWith("boxy-tee", "single"));
  });

  it("a colour-matrix pick made before the report lands falls back to single", async () => {
    /* The report is fetched, so the count arrives after the first paint. A
     * choice that is no longer available has to give way rather than be
     * submitted. */
    let resolveReport: (rows: ColourReportRow[]) => void = () => {};
    vi.spyOn(calibrator, "getColourReport").mockReturnValue(
      new Promise<ColourReportRow[]>((resolve) => {
        resolveReport = resolve;
      }),
    );
    renderPicker();

    fireEvent.click(screen.getByRole("radio", { name: /Colour Matrix/ }));
    expect(screen.getByRole("radio", { name: /Colour Matrix/ })).toBeChecked();

    resolveReport(ONE_PHOTO);
    await waitFor(() => expect(screen.getByRole("radio", { name: /Single/ })).toBeChecked());
  });
});

describe("KindPicker", () => {
  it("asks the question and offers the three kinds", async () => {
    renderPicker();
    expect(screen.getByText("What kind of template is this?")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Colour Matrix/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Multiple/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Single/ })).toBeInTheDocument();
  });

  it("explains what each kind means, since the names alone do not", () => {
    renderPicker();
    expect(screen.getByText("one photo per colour")).toBeInTheDocument();
    expect(screen.getByText("many garments, one photo")).toBeInTheDocument();
    expect(screen.getByText("one photo, one garment")).toBeInTheDocument();
  });

  it("shows the colour each filename yields, for the colour-matrix choice", async () => {
    renderPicker();
    await screen.findByText("sand.png");
    expect(screen.getByText("black.png")).toBeInTheDocument();
  });

  it("warns about a filename that is not already the slug", async () => {
    vi.spyOn(calibrator, "getColourReport").mockResolvedValue(MESSY);
    renderPicker();
    await screen.findByText("Heather Grey.png");
    expect(screen.getByText(/1 filename is not a colour slug/)).toBeInTheDocument();
  });

  it("says nothing about filenames when they are all clean", async () => {
    renderPicker();
    await screen.findByText("sand.png");
    expect(screen.queryByText(/is not a colour slug/)).not.toBeInTheDocument();
  });

  it("hides the colour report once a scene kind is chosen", async () => {
    renderPicker();
    await screen.findByText("sand.png");
    fireEvent.click(screen.getByRole("radio", { name: /Single/ }));
    // A scene kind has one photo and no colours to read off filenames
    // (PRD 28), so the report is not just irrelevant -- it is misleading.
    expect(screen.queryByText("sand.png")).not.toBeInTheDocument();
  });

  it("assigns the chosen kind and reports it upward", async () => {
    const assignSpy = vi.spyOn(calibrator, "assignKind").mockResolvedValue({
      kind: "colour-matrix",
      bounding_box: [
        { x: 0, y: 0 },
        { x: 1, y: 0 },
        { x: 1, y: 1 },
        { x: 0, y: 1 },
      ],
      displace: { enabled: false, strength: 0 },
      shade: { enabled: true, opacity: 0.6, blend: "soft-light" },
    });
    const { onAssigned } = renderPicker();

    fireEvent.click(screen.getByRole("button", { name: /Start calibrating/ }));
    await waitFor(() => expect(assignSpy).toHaveBeenCalledWith("boxy-tee", "colour-matrix"));
    await waitFor(() => expect(onAssigned).toHaveBeenCalled());
  });

  it("assigns whichever kind is actually selected", async () => {
    const assignSpy = vi.spyOn(calibrator, "assignKind").mockResolvedValue({
      kind: "multiple",
      colour_coverage: "exact",
      placements: [],
      displace: { enabled: false, strength: 0 },
      shade: { enabled: true, opacity: 0.6, blend: "soft-light" },
    });
    renderPicker();
    fireEvent.click(screen.getByRole("radio", { name: /Multiple/ }));
    fireEvent.click(screen.getByRole("button", { name: /Start calibrating/ }));
    await waitFor(() => expect(assignSpy).toHaveBeenCalledWith("boxy-tee", "multiple"));
  });

  it("reports a refusal instead of leaving the button dead", async () => {
    vi.spyOn(calibrator, "assignKind").mockRejectedValue(new Error("409"));
    renderPicker();
    fireEvent.click(screen.getByRole("button", { name: /Start calibrating/ }));
    await screen.findByText("could not set the kind");
  });

  it("survives the colour report failing", async () => {
    vi.spyOn(calibrator, "getColourReport").mockRejectedValue(new Error("network"));
    renderPicker();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Start calibrating/ })).toBeEnabled(),
    );
  });
});
