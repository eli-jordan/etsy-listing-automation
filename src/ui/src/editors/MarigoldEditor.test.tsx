import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../api/calibrator";
import * as preparation from "../api/preparation";
import { BOX, MARIGOLD, READY, SINGLE } from "../test/marigold";
import { must } from "../test/helpers";
import type { Renderer, TemplateConfigState } from "../types";
import { MarigoldEditor } from "./MarigoldEditor";

beforeEach(() => {
  vi.spyOn(calibrator, "listDesigns").mockResolvedValue([]);
  vi.spyOn(preparation, "getMaskHistory").mockResolvedValue({
    checksum: "mask",
    undo_count: 0,
    strokes: [],
  });
  vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:full");
});
afterEach(() => vi.restoreAllMocks());
function setup(config: TemplateConfigState = SINGLE, ready: preparation.Preparation = READY) {
  let current: TemplateConfigState = config;
  let edits: preparation.MaskEdit[] = [];
  function Harness() {
    const [value, setValue] = useState(config);
    const [mask, setMask] = useState<preparation.MaskEdit[]>([]);
    return (
      <MarigoldEditor
        templateName="tee"
        config={{ ...value, renderer: value.renderer as Extract<Renderer, { type: "marigold" }> }}
        savedConfig={config}
        space={[400, 200]}
        colours={["black", "white"]}
        knownColours={["black", "white"]}
        design="bundled-grid"
        onDesignChange={vi.fn()}
        onChange={(next) => {
          current = next;
          setValue(next);
        }}
        preparation={ready}
        rendererControls={<span>Renderer controls</span>}
        maskEdits={mask}
        onMaskEdits={(next) => {
          edits = next;
          setMask(next);
        }}
        onPrepare={vi.fn()}
      />
    );
  }
  const result = render(<Harness />);
  fireEvent.load(screen.getByAltText("Rendered preview"));
  return { ...result, config: () => current, edits: () => edits };
}
function pointerSpace(svg: SVGSVGElement) {
  Object.assign(svg, {
    getScreenCTM: () => ({ inverse: () => ({}) }),
    createSVGPoint: () => ({
      x: 0,
      y: 0,
      matrixTransform() {
        return { x: this.x * 2, y: this.y * 2 };
      },
    }),
  });
}
describe("MarigoldEditor", () => {
  it("calibrates locally without making a render request and hides only box chrome", () => {
    const { container } = setup();
    expect(calibrator.renderPreview).not.toHaveBeenCalled();
    expect(container.querySelector("foreignObject img")).toHaveAttribute(
      "src",
      "/api/designs/bundled-grid/image",
    );
    fireEvent.click(screen.getByRole("switch", { name: "Show design box" }));
    expect(container.querySelectorAll(".quad-editor__box")).toHaveLength(0);
    expect(container.querySelector("foreignObject img")).toBeInTheDocument();
  });
  it("retains whole photo-coordinate strokes on Done and Escape, Undo and Reset affect only the mask", () => {
    const view = setup();
    pointerSpace(must(view.container.querySelector<SVGSVGElement>("svg.quad-editor__overlay")));
    fireEvent.click(screen.getByText("Edit mask"));
    const area = screen.getByLabelText("Mask drawing area");
    fireEvent.pointerDown(area, { clientX: 20, clientY: 25, button: 0 });
    fireEvent.pointerMove(area, { clientX: 30, clientY: 35 });
    fireEvent.pointerUp(area);
    expect(view.edits()).toEqual([
      {
        placement_id: null,
        operations: [
          {
            type: "stroke",
            mode: "mask",
            diameter_px: 24,
            points: [
              [40, 50],
              [60, 70],
            ],
          },
        ],
      },
    ]);
    fireEvent.click(screen.getByText("Done"));
    expect(screen.queryByText("Red = hidden print")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Edit mask"));
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(screen.queryByRole("toolbar", { name: "Mask brushes" })).not.toBeInTheDocument();
    expect(view.edits()[0]?.operations).toHaveLength(1);
    fireEvent.click(screen.getByText("Edit mask"));
    fireEvent.click(screen.getByLabelText("Mask actions"));
    fireEvent.click(screen.getByText("Undo brush stroke"));
    expect(view.edits()[0]?.operations.at(-1)).toEqual({ type: "undo" });
    fireEvent.click(screen.getByLabelText("Mask actions"));
    expect(screen.getByText("Undo brush stroke")).toBeDisabled();
    fireEvent.click(screen.getByText("Reset mask"));
    expect(view.edits()[0]?.operations.at(-1)).toEqual({ type: "reset" });
    expect(view.config()).toEqual(SINGLE);
  });
  it("keeps stable placement IDs when duplicated, reordered and removed", () => {
    const config: TemplateConfigState = {
      kind: "multiple",
      colour_coverage: "exact",
      placements: [
        { id: "first", colour: "black", bounding_box: BOX, artwork: null },
        { id: "second", colour: "white", bounding_box: BOX, artwork: null },
      ],
      renderer: MARIGOLD,
    };
    const ready = {
      ...READY,
      placements: [
        { placement_id: "first", mask_available: true, mask_reason: null, undo_count: 0 },
        { placement_id: "second", mask_available: true, mask_reason: null, undo_count: 0 },
      ],
    };
    const view = setup(config, ready);
    fireEvent.contextMenu(must(view.container.querySelector(".quad-editor__box")));
    fireEvent.click(screen.getByText("Duplicate"));
    let next = view.config();
    expect(next.kind).toBe("multiple");
    if (next.kind !== "multiple") throw new Error("wrong kind");
    expect(next.placements.map((p) => p.id)).toEqual(["first", expect.any(String), "second"]);
    const copy = next.placements[1]?.id;
    expect(copy).not.toBe("first");
    fireEvent.contextMenu(must(view.container.querySelectorAll(".quad-editor__box")[1]));
    fireEvent.click(screen.getByText("Bring to front"));
    next = view.config();
    if (next.kind !== "multiple") throw new Error("wrong kind");
    expect(next.placements.map((p) => p.id)).toEqual(["first", "second", copy]);
    fireEvent.keyDown(must(view.container.querySelector(".quad-editor")), { key: "Delete" });
    next = view.config();
    if (next.kind !== "multiple") throw new Error("wrong kind");
    expect(next.placements.map((p) => p.id)).toEqual(["first", "second"]);
  });
  it("keeps the fixed main colour reference while browsing colours and previews all colours", async () => {
    setup({ kind: "colour-matrix", bounding_box: BOX, renderer: MARIGOLD });
    expect(screen.getByText(/Main photo.*main.png/)).toBeInTheDocument();
    expect(screen.queryByText("Colour")).not.toBeInTheDocument();
    expect(screen.getByAltText("Rendered preview")).toHaveAttribute(
      "src",
      "/api/templates/tee/photo",
    );
    fireEvent.click(screen.getByRole("tab", { name: "Preview" }));
    await waitFor(() => expect(calibrator.renderPreview).toHaveBeenCalledTimes(2));
  });
  it("allows unsaved appearance preview but blocks missing maps and unsaved mask edits", async () => {
    const view = setup();
    fireEvent.change(screen.getByLabelText("Fabric texture"), { target: { value: "60" } });
    fireEvent.click(screen.getByRole("tab", { name: "Preview" }));
    await waitFor(() => expect(calibrator.renderPreview).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("button", { name: "Re-render" })).toBeEnabled();
    fireEvent.click(screen.getByRole("tab", { name: "Calibrate" }));
    fireEvent.click(screen.getByText("Edit mask"));
    fireEvent.click(screen.getByLabelText("Mask actions"));
    fireEvent.click(screen.getByText("Reset mask"));
    fireEvent.click(screen.getByRole("tab", { name: "Preview" }));
    expect(screen.getByRole("button", { name: "Re-render" })).toBeDisabled();
    expect(view.edits()).toHaveLength(1);
  });
  it("does not infer or render when Preview opens with missing maps", async () => {
    setup(SINGLE, {
      ...READY,
      maps: {
        ...READY.maps,
        can_render: false,
        state: "needs_preparation",
        message: "Prepare the template first.",
      },
    });
    fireEvent.click(screen.getByRole("tab", { name: "Preview" }));
    await act(async () => {});
    expect(calibrator.renderPreview).not.toHaveBeenCalled();
    expect(screen.getByText("Prepare the template first.")).toBeInTheDocument();
  });
  it("shows a persisted stroke checkpoint immediately when Undo is drafted", async () => {
    vi.mocked(preparation.getMaskHistory).mockResolvedValue({
      checksum: "mask",
      undo_count: 1,
      strokes: [
        {
          before: "previouspng",
          operation: { type: "stroke", mode: "mask", diameter_px: 10, points: [[20, 20]] },
        },
      ],
    });
    const view = setup(SINGLE, {
      ...READY,
      placements: [{ ...must(READY.placements[0]), undo_count: 1 }],
    });
    await waitFor(() => expect(preparation.getMaskHistory).toHaveBeenCalled());
    await act(async () => {});
    fireEvent.click(screen.getByText("Edit mask"));
    fireEvent.click(screen.getByLabelText("Mask actions"));
    fireEvent.click(screen.getByText("Undo brush stroke"));
    expect(view.container.querySelector("mask image")).toHaveAttribute(
      "href",
      "data:image/png;base64,previouspng",
    );
  });
});

it("has one drawing area and assigns a multiple mask stroke to the selected stable ID", () => {
  const config: TemplateConfigState = {
    kind: "multiple",
    colour_coverage: "exact",
    placements: [
      { id: "first", colour: "black", bounding_box: BOX, artwork: null },
      { id: "second", colour: "white", bounding_box: BOX, artwork: null },
    ],
    renderer: MARIGOLD,
  };
  const ready = {
    ...READY,
    placements: config.placements.map((p) => ({
      placement_id: p.id,
      mask_available: true,
      mask_reason: null,
      undo_count: 0,
    })),
  };
  const view = setup(config, ready);
  fireEvent.click(must(view.container.querySelectorAll(".quad-editor__box")[1]));
  fireEvent.click(screen.getByText("Edit mask"));
  expect(view.container.querySelectorAll('[aria-label="Mask drawing area"]')).toHaveLength(1);
  pointerSpace(must(view.container.querySelector<SVGSVGElement>("svg.quad-editor__overlay")));
  const area = screen.getByLabelText("Mask drawing area");
  fireEvent.pointerDown(area, { button: 0, clientX: 250, clientY: 250 });
  fireEvent.pointerUp(area);
  expect(view.edits()).toEqual([
    {
      placement_id: "second",
      operations: [{ type: "stroke", mode: "mask", diameter_px: 24, points: [[399, 199]] }],
    },
  ]);
  fireEvent.keyDown(screen.getByRole("toolbar", { name: "Mask brushes" }), { key: "Escape" });
  expect(screen.queryByRole("toolbar", { name: "Mask brushes" })).not.toBeInTheDocument();
  expect(view.edits()).toHaveLength(1);
});

it("refuses an automatic full preview from Photo warp not-required status", async () => {
  setup(SINGLE, { ...READY, maps: { state: "not_required", can_render: true } });
  await act(async () => {});
  expect(calibrator.renderPreview).not.toHaveBeenCalled();
});
