import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../../../api/calibrator";
import * as listingsApi from "../../../api/listings";
import * as preparationApi from "../../../api/preparation";
import * as settingsApi from "../../../api/workspaceSettings";
import { listingDetail } from "../../../test/listings";
import type { ListingDetail, TemplateConfigState, TemplateSummary } from "../../../types";
import { must } from "../../../test/helpers";
import { ImagesTab } from "../ImagesTab";
import { type Quad, compose, decompose } from "./pose";

/**
 * Position mode on the Listing Images preview pane (interactions: *Entry and
 * the Adjust position switch*, *Adjusting*, *Multiple templates*, *Position
 * outside the limits*). The stage's rectangle is the photo's own size here,
 * so a pointer's client coordinates are photo pixels.
 */

const W = 480;
const H = 576;
const FOLDED_BOX = [
  { x: 100, y: 100 },
  { x: 300, y: 100 },
  { x: 300, y: 400 },
  { x: 100, y: 400 },
] as unknown as Quad;
const LEFT = [
  { x: 40, y: 100 },
  { x: 180, y: 100 },
  { x: 180, y: 300 },
  { x: 40, y: 300 },
] as unknown as Quad;
const RIGHT = [
  { x: 280, y: 100 },
  { x: 420, y: 100 },
  { x: 420, y: 300 },
  { x: 280, y: 300 },
] as unknown as Quad;

const photoWarp = { type: "photo-warp" } as TemplateConfigState["renderer"];

const CONFIGS: Record<string, TemplateConfigState> = {
  folded: { kind: "colour-matrix", labels: [], bounding_box: FOLDED_BOX, renderer: photoWarp },
  pair: {
    kind: "multiple",
    labels: [],
    colour_coverage: "exact",
    placements: [
      { id: "left-shirt", colour: "black", bounding_box: LEFT },
      { id: "right-shirt", colour: "white", bounding_box: RIGHT },
    ],
    renderer: photoWarp,
  } as TemplateConfigState,
  glossy: {
    kind: "single",
    labels: [],
    bounding_box: FOLDED_BOX,
    renderer: { type: "marigold" } as TemplateConfigState["renderer"],
  },
};

function summary(name: string, over: Partial<TemplateSummary> = {}): TemplateSummary {
  return {
    name,
    kind: must(CONFIGS[name]).kind,
    colours: ["black", "white"],
    photos: [],
    has_config: true,
    labels: [],
    status: "calibrated",
    status_reason: null,
    width: W,
    height: H,
    renderer: must(CONFIGS[name]).renderer.type,
    ...over,
  };
}

const LIMITS = { scale: { min: 0.8, max: 1.1 }, offset: 0.1, rotation: 15 };

function detail(over: Partial<ListingDetail> = {}): ListingDetail {
  return listingDetail({
    colors: ["black", "white"],
    design_content_hash: "d1",
    media: [
      { template: "folded", colour: "black" },
      { template: "folded", colour: "white" },
      { template: "pair", colour: null },
      { template: "glossy", colour: null },
      "common-media/size-chart.png",
    ],
    ...over,
  });
}

beforeEach(() => {
  vi.spyOn(listingsApi, "listCommonMedia").mockResolvedValue([]);
  vi.spyOn(listingsApi, "listListingMediaFiles").mockResolvedValue([]);
  vi.spyOn(calibrator, "listTemplates").mockResolvedValue([
    summary("folded"),
    summary("pair"),
    summary("glossy"),
  ]);
  vi.spyOn(calibrator, "getTemplateConfig").mockImplementation((name) =>
    Promise.resolve({ config: must(CONFIGS[name]), modifiedAt: "", revision: "r1" }),
  );
  vi.spyOn(settingsApi, "getSettings").mockResolvedValue({
    template_positions: LIMITS,
  } as unknown as settingsApi.WorkspaceSettings);
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({
    left: 0,
    top: 0,
    width: W,
    height: H,
    right: W,
    bottom: H,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

interface Mounted {
  onUpdate: ReturnType<typeof vi.fn>;
  onFlush: ReturnType<typeof vi.fn>;
  rerender: (next: ListingDetail) => void;
}

function mount(listing: ListingDetail = detail()): Mounted {
  const onUpdate = vi.fn();
  const onFlush = vi.fn(() => Promise.resolve());
  const view = render(<ImagesTab detail={listing} onUpdate={onUpdate} onFlush={onFlush} />);
  return {
    onUpdate,
    onFlush,
    rerender: (next) =>
      view.rerender(<ImagesTab detail={next} onUpdate={onUpdate} onFlush={onFlush} />),
  };
}

async function selectTile(label: string) {
  const reel = document.querySelector<HTMLElement>(".reel__track");
  if (reel === null) throw new Error("no reel");
  fireEvent.click(await within(reel).findByRole("img", { name: label }));
}

/** The picture the preview pane is showing, whichever element draws it. */
function stagePicture(): string | null {
  const stage = document.querySelector(".preview-stage");
  const img = stage?.querySelector("img");
  return img?.getAttribute("src") ?? stage?.querySelector("image")?.getAttribute("href") ?? null;
}

const adjustSwitch = () => screen.findByRole("switch", { name: "Adjust position" });

async function adjust(label: string) {
  await selectTile(label);
  fireEvent.click(await adjustSwitch());
  return screen.findByRole("button", { name: /position — drag to move/ });
}

/** The pose the last save wrote for `template` (or a placement of it). */
function savedPose(onUpdate: Mounted["onUpdate"], box: Quad, path: string[]) {
  const positions = onUpdate.mock.lastCall?.[0].template_positions as Record<string, unknown>;
  const entry = path.reduce<unknown>((at, key) => (at as Record<string, unknown>)[key], positions);
  return decompose(box, (entry as { bounding_box: Quad }).bounding_box).pose;
}

describe("the Adjust position switch", () => {
  it("is offered for a template entry in the listing, off to begin with", async () => {
    mount();
    await selectTile("folded · black");
    expect(await adjustSwitch()).toHaveAttribute("aria-checked", "false");
    expect(screen.queryByRole("button", { name: /position — drag to move/ })).toBeNull();
  });

  it("is offered for a Marigold template too", async () => {
    mount();
    await selectTile("glossy");
    expect(await adjustSwitch()).toHaveAttribute("aria-checked", "false");
  });

  it("is absent for a file ref", async () => {
    vi.spyOn(listingsApi, "listCommonMedia").mockResolvedValue([
      {
        name: "size-chart.png",
        file: "common-media/size-chart.png",
        ref: "common-media/size-chart.png",
        kind: "image",
      },
    ]);
    mount();
    await selectTile("folded · black");
    await adjustSwitch();
    await selectTile("size-chart");
    await waitFor(() =>
      expect(screen.queryByRole("switch", { name: "Adjust position" })).toBeNull(),
    );
  });

  it("turns off when another reel tile is selected", async () => {
    mount();
    await adjust("folded · black");
    await selectTile("folded · white");
    expect(await adjustSwitch()).toHaveAttribute("aria-checked", "false");
  });

  it("shows the composite of the saved listing, signed by the saved position", async () => {
    const { rerender } = mount();
    await selectTile("folded · black");
    const before = stagePicture();
    expect(before).toContain("scene-preview");

    const moved = compose(FOLDED_BOX, { scale: 0.9, offsetX: 0, offsetY: 0, rotation: 0 });
    rerender(
      detail({
        template_positions: { folded: { bounding_box: moved } },
        modified_at: "2026-09-17T10:05:00Z",
      }),
    );
    const after = stagePicture();
    expect(after).not.toEqual(before);
  });
});

describe("a Marigold template not ready for positions", () => {
  const ready = { ready: true, preparing: false };
  const preparing = { ready: false, preparing: true };
  const uncovered = { ready: false, preparing: false };
  const note = "This template is being prepared. Adjusting will be available soon.";

  async function refusedSwitch() {
    mount();
    await selectTile("glossy");
    const control = await adjustSwitch();
    await waitFor(() => expect(control).toHaveAttribute("aria-disabled", "true"));
    fireEvent.click(control);
    return control;
  }

  it("stays off and says why while preparation is running", async () => {
    vi.spyOn(preparationApi, "getPositionReadiness").mockResolvedValue(preparing);
    const queue = vi.spyOn(preparationApi, "queueCoverage").mockResolvedValue(null);
    const control = await refusedSwitch();
    expect(await screen.findByText(note)).toBeInTheDocument();
    expect(control).toHaveAttribute("aria-checked", "false");
    expect(screen.queryByRole("button", { name: /position — drag to move/ })).toBeNull();
    expect(queue).not.toHaveBeenCalled();
  });

  it("starts the preparation it is waiting for when nothing is running", async () => {
    vi.spyOn(preparationApi, "getPositionReadiness").mockResolvedValue(uncovered);
    const queue = vi
      .spyOn(preparationApi, "queueCoverage")
      .mockResolvedValue({ id: "job" } as preparationApi.PreparationJob);
    await refusedSwitch();
    expect(await screen.findByText(note)).toBeInTheDocument();
    expect(queue).toHaveBeenCalledExactlyOnceWith("glossy");
  });

  it("says so when the preparation cannot start", async () => {
    vi.spyOn(preparationApi, "getPositionReadiness").mockResolvedValue(uncovered);
    vi.spyOn(preparationApi, "queueCoverage").mockResolvedValue(null);
    await refusedSwitch();
    expect(await screen.findByText(/could not start/)).toBeInTheDocument();
  });

  it("works again, with the note gone, once the template is ready", async () => {
    const read = vi.spyOn(preparationApi, "getPositionReadiness").mockResolvedValue(preparing);
    const control = await refusedSwitch();
    await screen.findByText(note);
    read.mockResolvedValue(ready);
    await waitFor(() => expect(control).toHaveAttribute("aria-disabled", "false"), {
      timeout: 5000,
    });
    expect(screen.queryByText(note)).toBeNull();
    fireEvent.click(control);
    expect(control).toHaveAttribute("aria-checked", "true");
  }, 8000);

  it("shows a placeholder for a picture it cannot load, then tries it again", async () => {
    const read = vi.spyOn(preparationApi, "getPositionReadiness").mockResolvedValue(ready);
    mount();
    await selectTile("glossy");
    await adjustSwitch();
    read.mockResolvedValue(preparing);
    fireEvent.error(must(document.querySelector(".preview-stage img")));
    expect(
      await screen.findByText("This picture will appear when preparation finishes"),
    ).toBeInTheDocument();
    read.mockResolvedValue(ready);
    await waitFor(() => expect(stagePicture()).not.toBeNull(), { timeout: 5000 });
  }, 8000);

  it("says a picture could not load when nothing is being prepared", async () => {
    vi.spyOn(preparationApi, "getPositionReadiness").mockResolvedValue(ready);
    mount();
    await selectTile("glossy");
    await adjustSwitch();
    fireEvent.error(must(document.querySelector(".preview-stage img")));
    expect(await screen.findByText("This picture could not load")).toBeInTheDocument();
  });
});

describe("adjusting a position", () => {
  it("shows handles but no ghost or Reset while the listing has no position", async () => {
    mount();
    await adjust("folded · black");
    expect(screen.getAllByLabelText("Drag to resize")).toHaveLength(4);
    expect(screen.getByLabelText("Drag to tilt")).toBeInTheDocument();
    expect(document.querySelector(".tp-ghost")).toBeNull();
    expect(screen.queryByRole("button", { name: "Reset to template" })).toBeNull();
    expect(screen.getByText("Applies to all 2 folded colours in this listing")).toBeInTheDocument();
  });

  it("saves a move once, on pointer release", async () => {
    const { onUpdate, onFlush } = mount();
    const box = await adjust("folded · black");
    fireEvent.pointerDown(box, { clientX: 200, clientY: 250, pointerId: 1, button: 0 });
    fireEvent.pointerMove(box, { clientX: 210, clientY: 250, pointerId: 1 });
    fireEvent.pointerMove(box, { clientX: 220, clientY: 235, pointerId: 1 });
    expect(onUpdate).not.toHaveBeenCalled();
    expect(document.querySelector(".tp-overlay")).not.toBeNull();
    fireEvent.pointerUp(box, { clientX: 220, clientY: 235, pointerId: 1 });

    expect(onUpdate).toHaveBeenCalledTimes(1);
    expect(onFlush).toHaveBeenCalledTimes(1);
    const pose = savedPose(onUpdate, FOLDED_BOX, ["folded"]);
    expect(pose.offsetX).toBeCloseTo(0.1, 6);
    expect(pose.offsetY).toBeCloseTo(-0.05, 6);
  });

  it("resizes uniformly from a corner and stops at the limit", async () => {
    const { onUpdate } = mount();
    await adjust("folded · black");
    const corner = must(screen.getAllByLabelText("Drag to resize")[2]);
    fireEvent.pointerDown(corner, { clientX: 300, clientY: 400, pointerId: 1, button: 0 });
    fireEvent.pointerMove(corner, { clientX: 400, clientY: 550, pointerId: 1 });
    fireEvent.pointerUp(corner, { clientX: 400, clientY: 550, pointerId: 1 });
    expect(savedPose(onUpdate, FOLDED_BOX, ["folded"]).scale).toBeCloseTo(1.1, 6);
  });

  it("tilts in whole degrees", async () => {
    const { onUpdate } = mount();
    await adjust("folded · black");
    const handle = screen.getByLabelText("Drag to tilt");
    fireEvent.pointerDown(handle, { clientX: 200, clientY: 80, pointerId: 1, button: 0 });
    // 20 px right of the centre and 150 px above it: 7.59 degrees, rounded to 8.
    fireEvent.pointerMove(handle, { clientX: 220, clientY: 100, pointerId: 1 });
    fireEvent.pointerUp(handle, { clientX: 220, clientY: 100, pointerId: 1 });
    expect(savedPose(onUpdate, FOLDED_BOX, ["folded"]).rotation).toBeCloseTo(8, 6);
  });

  it("debounces arrow-key nudges into one save", async () => {
    const { onUpdate } = mount();
    const box = await adjust("folded · black");
    vi.useFakeTimers();
    fireEvent.keyDown(box, { key: "ArrowRight" });
    fireEvent.keyDown(box, { key: "ArrowRight" });
    fireEvent.keyDown(box, { key: "ArrowDown", shiftKey: true });
    expect(onUpdate).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(400));
    expect(onUpdate).toHaveBeenCalledTimes(1);
    const pose = savedPose(onUpdate, FOLDED_BOX, ["folded"]);
    expect(pose.offsetX).toBeCloseTo(0.02, 6);
    expect(pose.offsetY).toBeCloseTo(0.05, 6);
  });

  it("writes the template's own box as no entry", async () => {
    const shifted = compose(FOLDED_BOX, { scale: 1, offsetX: 0.01, offsetY: 0, rotation: 0 });
    const { onUpdate } = mount(
      detail({ template_positions: { folded: { bounding_box: shifted } } }),
    );
    const box = await adjust("folded · black");
    vi.useFakeTimers();
    fireEvent.keyDown(box, { key: "ArrowLeft" });
    act(() => vi.advanceTimersByTime(400));
    expect(onUpdate).toHaveBeenCalledWith({ template_positions: null });
  });

  it("shows the ghost and resets to the template by removing the entry", async () => {
    const moved = compose(FOLDED_BOX, { scale: 0.9, offsetX: 0.05, offsetY: 0, rotation: 4 });
    const positions = { folded: { bounding_box: moved }, pair: { placements: {} } };
    const { onUpdate, onFlush } = mount(detail({ template_positions: positions }));
    await adjust("folded · black");
    expect(document.querySelector(".tp-ghost")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Reset to template" }));
    expect(onUpdate).toHaveBeenCalledWith({ template_positions: { pair: { placements: {} } } });
    expect(onFlush).toHaveBeenCalled();
  });

  it("never shows the drag overlay with the switch off", async () => {
    mount();
    await selectTile("folded · black");
    await adjustSwitch();
    expect(document.querySelector(".tp-overlay")).toBeNull();
    expect(screen.queryAllByLabelText("Drag to resize")).toHaveLength(0);
  });
});

describe("a multiple template", () => {
  it("edits the first placement and selects another by clicking it", async () => {
    const { onUpdate } = mount();
    await adjust("pair");
    expect(screen.getByText("Click the other shirt to switch")).toBeInTheDocument();
    expect(screen.getByText("right-shirt")).toBeInTheDocument();
    fireEvent.pointerDown(screen.getByRole("button", { name: "Select right-shirt" }), {
      pointerId: 1,
      button: 0,
    });
    expect(screen.getByText("left-shirt")).toBeInTheDocument();

    const box = screen.getByRole("button", { name: /position — drag to move/ });
    vi.useFakeTimers();
    fireEvent.keyDown(box, { key: "ArrowUp" });
    act(() => vi.advanceTimersByTime(400));
    expect(savedPose(onUpdate, RIGHT, ["pair", "placements", "right-shirt"]).offsetY).toBeCloseTo(
      -0.01,
      6,
    );
  });

  it("resets only the selected placement", async () => {
    const left = compose(LEFT, { scale: 0.9, offsetX: 0, offsetY: 0, rotation: 0 });
    const right = compose(RIGHT, { scale: 0.9, offsetX: 0, offsetY: 0, rotation: 0 });
    const { onUpdate } = mount(
      detail({
        template_positions: {
          pair: {
            placements: {
              "left-shirt": { bounding_box: left },
              "right-shirt": { bounding_box: right },
            },
          },
        },
      }),
    );
    await adjust("pair");
    fireEvent.click(screen.getByRole("button", { name: "Reset left-shirt" }));
    expect(onUpdate).toHaveBeenCalledWith({
      template_positions: { pair: { placements: { "right-shirt": { bounding_box: right } } } },
    });
  });
});

describe("a stored position outside the limits", () => {
  const stale = compose(FOLDED_BOX, { scale: 1.2, offsetX: -0.11, offsetY: 0, rotation: 0 });

  it("opens in Position mode with a red box, a note and Fit within limits", async () => {
    const { onUpdate } = mount(detail({ template_positions: { folded: { bounding_box: stale } } }));
    await selectTile("folded · black");
    expect(await adjustSwitch()).toHaveAttribute("aria-checked", "true");
    expect(document.querySelector(".tp-box--invalid")).not.toBeNull();
    expect(
      screen.getByText("Outside the limits since the template's box moved"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Fit within limits" }));
    const pose = savedPose(onUpdate, FOLDED_BOX, ["folded"]);
    expect(pose.scale).toBeCloseTo(1.1, 6);
    expect(pose.offsetX).toBeCloseTo(-0.1, 6);
    expect(await adjustSwitch()).toHaveAttribute("aria-checked", "true");
  });

  it("stays in Position mode once a nudge brings it within limits", async () => {
    const { onUpdate, rerender } = mount(
      detail({ template_positions: { folded: { bounding_box: stale } } }),
    );
    await selectTile("folded · black");
    const box = await screen.findByRole("button", { name: /position — drag to move/ });
    vi.useFakeTimers();
    fireEvent.keyDown(box, { key: "ArrowRight" });
    // The draft must not unmount the box under the keyboard mid-gesture.
    expect(document.contains(box)).toBe(true);
    act(() => vi.advanceTimersByTime(400));
    const saved = onUpdate.mock.lastCall?.[0] as {
      template_positions: ListingDetail["template_positions"];
    };
    rerender(detail({ template_positions: saved.template_positions ?? null }));

    expect(screen.getByRole("switch", { name: "Adjust position" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(document.querySelector(".tp-box--invalid")).toBeNull();
  });

  it("says so when the box is not a plain move, resize or tilt", async () => {
    const skewed = [...FOLDED_BOX] as unknown as Quad[number][];
    skewed[2] = { x: 330, y: 400 };
    mount(detail({ template_positions: { folded: { bounding_box: skewed as unknown as Quad } } }));
    await selectTile("folded · black");
    await waitFor(() =>
      expect(
        screen.getByText("Not a plain move, resize or tilt of the template's box"),
      ).toBeInTheDocument(),
    );
  });
});

describe("the gallery", () => {
  it("badges every tile of a template this listing positions", async () => {
    const moved = compose(FOLDED_BOX, { scale: 0.9, offsetX: 0, offsetY: 0, rotation: 0 });
    mount(detail({ template_positions: { folded: { bounding_box: moved } } }));
    await screen.findAllByRole("img", { name: "folded · black" });
    expect(screen.getAllByTitle("This listing positions the design on this template")).toHaveLength(
      2,
    );
  });
});
