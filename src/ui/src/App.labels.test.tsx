import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import * as calibrator from "./api/calibrator";
import * as prep from "./api/preparation";
import { AUTOSAVE_DEBOUNCE_MS } from "./hooks/writeLoop";
import { PREVIEW_DEBOUNCE_MS } from "./hooks/usePreview";
import { controlledClock } from "./test/clock";
import { deferred } from "./test/helpers";
import { READY, SINGLE } from "./test/marigold";
import type { TemplateConfigState, TemplateSummary } from "./types";

const READ = "sha256:read";
const SAVED = "sha256:saved";

function summary(over: Partial<TemplateSummary> = {}): TemplateSummary {
  return {
    name: "tee",
    kind: "single",
    colours: [],
    photos: [],
    has_config: true,
    labels: [],
    status: "calibrated",
    status_reason: null,
    width: 400,
    height: 200,
    ...over,
  };
}

function opening(config: TemplateConfigState) {
  vi.mocked(calibrator.getTemplateConfig).mockResolvedValue({
    config,
    modifiedAt: "Wed, 17 Sep 2026 18:30:00 GMT",
    revision: READ,
  });
}

function bar() {
  return within(screen.getByRole("group", { name: "Labels" }));
}

function header() {
  return within(screen.getByRole("banner"));
}

/** Types a label with no suggestion to take its place, and presses Enter. */
async function addLabel(text: string) {
  fireEvent.click(await screen.findByRole("button", { name: "Add label" }));
  const field = screen.getByRole("textbox", { name: "Add a label" });
  fireEvent.change(field, { target: { value: text } });
  fireEvent.keyDown(field, { key: "Enter" });
}

function previews(scale: "editor" | "full") {
  return vi.mocked(calibrator.renderPreview).mock.calls.filter((call) => call[3] === scale);
}

beforeEach(() => {
  vi.spyOn(calibrator, "listTemplates").mockResolvedValue([summary()]);
  vi.spyOn(calibrator, "listDesigns").mockResolvedValue([]);
  vi.spyOn(calibrator, "getPositionedListings").mockResolvedValue([]);
  vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
  vi.spyOn(calibrator, "getTemplateConfig");
  opening(SINGLE);
  vi.spyOn(calibrator, "saveTemplateConfig").mockImplementation(async (_name, config) => ({
    config,
    revision: SAVED,
  }));
  vi.spyOn(prep, "getPreparation").mockResolvedValue({ ...READY, config_revision: READ });
  vi.spyOn(prep, "getRuntime").mockResolvedValue({
    available: true,
    problem: null,
    engine_version: "engine",
    required_engine: "engine",
    installation_id: "installed",
    max_num_inference_steps: 50,
    max_ensemble_size: 10,
    max_image_dimension: 4096,
    update_available: false,
  });
  vi.spyOn(prep, "listPreparationJobs").mockResolvedValue([]);
  vi.spyOn(prep, "getMaskHistory").mockResolvedValue({
    checksum: "mask",
    undo_count: 0,
    strokes: [],
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("the Labels bar", () => {
  it("stays hidden until the template has a kind", async () => {
    vi.mocked(calibrator.listTemplates).mockResolvedValue([
      summary({ kind: null, has_config: false, status: "needs-calibration" }),
    ]);
    vi.mocked(calibrator.getTemplateConfig).mockResolvedValue(null);
    vi.spyOn(calibrator, "getColourReport").mockResolvedValue([]);

    render(<App />);

    await screen.findByText("What kind of template is this?");
    expect(screen.queryByRole("group", { name: "Labels" })).not.toBeInTheDocument();
  });

  it("stays on show on both Calibrate and Preview", async () => {
    opening({ ...SINGLE, labels: ["cosy"] });
    render(<App />);
    await screen.findByRole("group", { name: "Labels" });

    fireEvent.click(screen.getByRole("tab", { name: "Preview" }));

    expect(bar().getByText("cosy")).toBeInTheDocument();
  });

  it("suggests labels from the catalog", async () => {
    vi.mocked(calibrator.listTemplates).mockResolvedValue([
      summary(),
      summary({ name: "other", labels: ["theme:christmas"] }),
    ]);
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Add label" }));

    expect(screen.getByRole("option", { name: "theme:christmas" })).toBeInTheDocument();
  });

  it("shows a chip only once the save lands, and refreshes the rail", async () => {
    const clock = controlledClock();
    render(<App />);
    await addLabel("cosy");
    vi.mocked(calibrator.listTemplates).mockResolvedValue([summary({ labels: ["cosy"] })]);

    expect(bar().queryByText("cosy")).not.toBeInTheDocument();
    expect(header().getByRole("status")).toHaveTextContent("Saving…");

    await clock.advance(AUTOSAVE_DEBOUNCE_MS);

    await waitFor(() => expect(bar().getByText("cosy")).toBeInTheDocument());
    expect(calibrator.saveTemplateConfig).toHaveBeenCalledTimes(1);
    expect(calibrator.saveTemplateConfig).toHaveBeenCalledWith(
      "tee",
      { ...SINGLE, labels: ["cosy"] },
      [],
      READ,
    );
    await waitFor(() =>
      expect(within(screen.getByRole("navigation")).getByText("cosy")).toBeInTheDocument(),
    );
  });

  it("removes a chip only once the save lands", async () => {
    opening({ ...SINGLE, labels: ["cosy"] });
    const clock = controlledClock();
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Remove cosy" }));
    expect(bar().getByText("cosy")).toBeInTheDocument();

    await clock.advance(AUTOSAVE_DEBOUNCE_MS);
    await waitFor(() => expect(bar().queryByText("cosy")).not.toBeInTheDocument());
  });

  it("leaves chips as they were on a failed save, with the error beside the bar", async () => {
    const write = vi
      .mocked(calibrator.saveTemplateConfig)
      .mockRejectedValue(new calibrator.CalibratorApiError("could not save template.yaml"));
    const clock = controlledClock();
    render(<App />);
    await addLabel("cosy");

    await clock.advance(AUTOSAVE_DEBOUNCE_MS);

    await waitFor(() =>
      expect(bar().getByRole("alert")).toHaveTextContent("could not save template.yaml"),
    );
    expect(bar().queryByText("cosy")).not.toBeInTheDocument();

    write.mockImplementation(async (_name, config) => ({ config, revision: SAVED }));
    await addLabel("warm");
    await clock.advance(AUTOSAVE_DEBOUNCE_MS);

    await waitFor(() => expect(bar().getByText("cosy")).toBeInTheDocument());
    expect(bar().getByText("warm")).toBeInTheDocument();
    expect(bar().queryByRole("alert")).not.toBeInTheDocument();
  });

  it("offers today's Reload template for a conflict, which discards the draft", async () => {
    vi.mocked(calibrator.saveTemplateConfig).mockRejectedValue(
      new calibrator.TemplateConflictError(),
    );
    const clock = controlledClock();
    render(<App />);
    await addLabel("cosy");

    await clock.advance(AUTOSAVE_DEBOUNCE_MS);

    await waitFor(() =>
      expect(bar().getByRole("alert")).toHaveTextContent("Template changed elsewhere."),
    );
    fireEvent.click(screen.getByRole("button", { name: "Reload template" }));
    await waitFor(() => expect(calibrator.getTemplateConfig).toHaveBeenCalledTimes(2));
    await screen.findByRole("group", { name: "Labels" });
    expect(bar().queryByRole("alert")).not.toBeInTheDocument();
  });

  it("says nothing beside the bar when a save of something else fails", async () => {
    vi.mocked(calibrator.saveTemplateConfig).mockRejectedValue(
      new calibrator.CalibratorApiError("could not save template.yaml"),
    );
    const clock = controlledClock();
    render(<App />);
    const texture = await screen.findByLabelText("Fabric texture");
    await clock.advance(PREVIEW_DEBOUNCE_MS);

    fireEvent.change(texture, { target: { value: "62" } });
    await clock.advance(PREVIEW_DEBOUNCE_MS);
    await clock.advance(AUTOSAVE_DEBOUNCE_MS);

    await waitFor(() =>
      expect(header().getByRole("status")).toHaveTextContent("could not save template.yaml"),
    );
    expect(bar().queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("a label save and the calibrator's preview", () => {
  it("sends the labels of the revision a preview names", async () => {
    opening({ ...SINGLE, labels: ["cosy"] });
    render(<App />);

    await waitFor(() => expect(previews("editor")).toHaveLength(1));

    expect(previews("editor")[0]?.[1]).toMatchObject({
      calibration_revision: READ,
      labels: ["cosy"],
    });
  });

  it("neither re-fetches nor blocks either view", async () => {
    const clock = controlledClock();
    render(<App />);
    await screen.findByRole("group", { name: "Labels" });
    await clock.advance(PREVIEW_DEBOUNCE_MS);
    fireEvent.click(screen.getByRole("tab", { name: "Preview" }));
    await waitFor(() => expect(previews("full")).toHaveLength(1));
    expect(previews("editor")).toHaveLength(1);
    const reads = vi.mocked(prep.getPreparation).mock.calls.length;

    await addLabel("cosy");
    await clock.advance(PREVIEW_DEBOUNCE_MS);
    await clock.advance(AUTOSAVE_DEBOUNCE_MS);
    await waitFor(() => expect(bar().getByText("cosy")).toBeInTheDocument());
    await clock.advance(PREVIEW_DEBOUNCE_MS);

    expect(screen.queryByText(/Waiting for current calibration status/)).not.toBeInTheDocument();
    expect(prep.getPreparation).toHaveBeenCalledTimes(reads);

    // Any later read reports the revision the label save moved the file to.
    vi.mocked(prep.getPreparation).mockResolvedValue({ ...READY, config_revision: SAVED });
    await act(async () => window.dispatchEvent(new Event("focus")));
    await waitFor(() => expect(prep.getPreparation).toHaveBeenCalledTimes(reads + 1));
    await clock.advance(PREVIEW_DEBOUNCE_MS);

    expect(screen.queryByText(/Waiting for current calibration status/)).not.toBeInTheDocument();
    expect(previews("editor")).toHaveLength(1);
    expect(previews("full")).toHaveLength(1);
  });

  it("keeps the frame already on the way when the save lands first", async () => {
    const frame = deferred<string>();
    vi.mocked(calibrator.renderPreview).mockReturnValue(frame.promise);
    const clock = controlledClock();
    render(<App />);
    await screen.findByRole("group", { name: "Labels" });
    await clock.advance(PREVIEW_DEBOUNCE_MS);
    expect(previews("editor")).toHaveLength(1);

    await addLabel("cosy");
    await clock.advance(AUTOSAVE_DEBOUNCE_MS);
    expect(calibrator.saveTemplateConfig).not.toHaveBeenCalled();

    await act(async () => frame.resolve("blob:frame"));
    await clock.advance(0);
    await waitFor(() => expect(bar().getByText("cosy")).toBeInTheDocument());
    await clock.advance(PREVIEW_DEBOUNCE_MS);

    expect(previews("editor")).toHaveLength(1);
    expect(screen.getByAltText("Rendered preview")).toHaveAttribute("src", "blob:frame");
  });

  it("keeps the status on show while a pending preview holds the save", async () => {
    const frame = deferred<string>();
    vi.mocked(calibrator.renderPreview).mockReturnValue(frame.promise);
    const clock = controlledClock();
    render(<App />);
    await screen.findByRole("group", { name: "Labels" });
    await clock.advance(PREVIEW_DEBOUNCE_MS);

    await addLabel("cosy");
    await clock.advance(AUTOSAVE_DEBOUNCE_MS * 3);

    expect(calibrator.saveTemplateConfig).not.toHaveBeenCalled();
    expect(header().getByRole("status")).toHaveTextContent("Saving…");
    expect(bar().queryByText("cosy")).not.toBeInTheDocument();

    await act(async () => frame.resolve("blob:frame"));
    await clock.advance(0);
    await waitFor(() => expect(bar().getByText("cosy")).toBeInTheDocument());
    expect(header().getByRole("status")).toHaveTextContent(/^Saved/);
  });
});
