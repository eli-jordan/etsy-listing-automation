import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../api/calibrator";
import { must } from "../test/helpers";
import type { MultipleTemplate } from "../types";
import { MultipleEditor } from "./MultipleEditor";

const SPACE: [number, number] = [400, 200];

const CONFIG: MultipleTemplate = {
  kind: "multiple",
  colour_coverage: "exact",
  placements: [
    {
      colour: "black",
      bounding_box: [
        { x: 0, y: 0 },
        { x: 100, y: 0 },
        { x: 100, y: 100 },
        { x: 0, y: 100 },
      ],
    },
  ],
  displace: { enabled: false, strength: 0 },
  shade: { enabled: true, opacity: 0.6, blend: "soft-light" },
};

afterEach(() => vi.restoreAllMocks());

beforeEach(() => {
  // The inspector now carries the test-design picker, which fetches the
  // library on mount. Stubbed so these tests stay about the editor.
  vi.spyOn(calibrator, "listDesigns").mockResolvedValue([]);
});

/** The canvas draws at the image's natural size, which jsdom never reports
 * for itself -- so a test that touches a box or its caption has to say what
 * the preview PNG was. */
function loadPreview(img: HTMLElement): void {
  Object.defineProperty(img, "naturalWidth", { value: 960, configurable: true });
  Object.defineProperty(img, "naturalHeight", { value: 576, configurable: true });
  fireEvent.load(img);
}

describe("MultipleEditor", () => {
  it("fetches a preview of the whole scene (all placements, no colour selector)", async () => {
    const spy = vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    render(
      <MultipleEditor
        templateName="colour-chart-01"
        config={CONFIG}
        space={SPACE}
        onChange={vi.fn()}
        design="bundled-grid"
        onDesignChange={vi.fn()}
        knownColours={[]}
      />,
    );

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        "colour-chart-01",
        {
          placements: CONFIG.placements,
          displace: CONFIG.displace,
          shade: CONFIG.shade,
        },
        "bundled-grid",
        "editor",
      ),
    );
  });

  it("adding a box from the canvas appends a placement", async () => {
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    const onChange = vi.fn();
    render(
      <MultipleEditor
        templateName="colour-chart-01"
        config={CONFIG}
        space={SPACE}
        onChange={onChange}
        design="bundled-grid"
        onDesignChange={vi.fn()}
        knownColours={[]}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "+ Add box" }));
    expect(must(onChange.mock.calls[0])[0].placements).toHaveLength(2);
  });

  /** The colour is the one thing about a placement the photo cannot show, and
   * it is now a caption on the box rather than a field in a side panel. */
  it("editing a box's caption assigns that placement's colour", async () => {
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    const onChange = vi.fn();
    render(
      <MultipleEditor
        templateName="colour-chart-01"
        config={CONFIG}
        space={SPACE}
        onChange={onChange}
        design="bundled-grid"
        onDesignChange={vi.fn()}
        knownColours={["ivory"]}
      />,
    );

    loadPreview(await screen.findByAltText("Rendered preview"));
    fireEvent.click(screen.getByRole("button", { name: "black" }));
    fireEvent.change(screen.getByLabelText("Colour for box 1"), { target: { value: "ivory" } });

    expect(must(onChange.mock.calls[0])[0].placements[0].colour).toBe("ivory");
  });

  it("says how many boxes still have no colour", async () => {
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    const config: MultipleTemplate = {
      ...CONFIG,
      placements: [...CONFIG.placements, { ...must(CONFIG.placements[0]), colour: "" }],
    };
    render(
      <MultipleEditor
        templateName="colour-chart-01"
        config={config}
        space={SPACE}
        onChange={vi.fn()}
        design="bundled-grid"
        onDesignChange={vi.fn()}
        knownColours={[]}
      />,
    );

    expect(
      await screen.findByText("1 box has no colour — can't mark calibrated yet"),
    ).toBeInTheDocument();
  });

  it("offers the empty state, not a canvas, when the photo has no boxes", async () => {
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    render(
      <MultipleEditor
        templateName="colour-chart-01"
        config={{ ...CONFIG, placements: [] }}
        space={SPACE}
        onChange={vi.fn()}
        design="bundled-grid"
        onDesignChange={vi.fn()}
        knownColours={[]}
      />,
    );

    expect(await screen.findByText("No bounding boxes on this photo")).toBeInTheDocument();
  });
});
