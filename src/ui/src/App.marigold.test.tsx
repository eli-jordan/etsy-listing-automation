import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import * as calibrator from "./api/calibrator";
import * as prep from "./api/preparation";
import { READY, SINGLE } from "./test/marigold";

const PHOTOWARP = {
  type: "photo-warp" as const,
  config: {
    displace: { enabled: true, strength: 0.2 },
    shade: { enabled: true, opacity: 0.8, blend: "multiply" as const },
  },
};
beforeEach(() => {
  vi.spyOn(calibrator, "listTemplates").mockResolvedValue([
    {
      name: "tee",
      kind: "single",
      colours: [],
      photos: [],
      has_config: true,
      status: "calibrated",
      status_reason: null,
      width: 400,
      height: 200,
    },
  ]);
  vi.spyOn(calibrator, "listDesigns").mockResolvedValue([]);
  vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
  vi.spyOn(calibrator, "getTemplateConfig").mockResolvedValue({
    config: { ...SINGLE, renderer: PHOTOWARP },
    modifiedAt: "Wed, 17 Sep 2026 18:30:00 GMT",
  });
  vi.spyOn(calibrator, "saveTemplateConfig").mockImplementation(async (_name, value) => value);
  vi.spyOn(prep, "getPreparation").mockResolvedValue({
    ...READY,
    maps: { ...READY.maps, can_render: false, state: "needs_preparation" },
    renderer_settings: {},
  });
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
describe("App Marigold workflow", () => {
  it("restores inactive renderer settings and never prepares on selection", async () => {
    const start = vi.spyOn(prep, "prepareTemplate");
    render(<App />);
    await screen.findByLabelText("Renderer");
    fireEvent.change(screen.getByLabelText("Renderer"), { target: { value: "marigold" } });
    expect(screen.getByText("Advanced settings", { exact: false })).toBeInTheDocument();
    expect(screen.getByLabelText("Fabric texture")).toHaveValue("25");
    fireEvent.change(screen.getByLabelText("Fabric texture"), { target: { value: "62" } });
    fireEvent.change(screen.getByLabelText("Renderer"), { target: { value: "photo-warp" } });
    expect(screen.getByLabelText("Wrinkle strength")).toHaveValue("20");
    fireEvent.change(screen.getByLabelText("Renderer"), { target: { value: "marigold" } });
    expect(screen.getByLabelText("Fabric texture")).toHaveValue("62");
    expect(start).not.toHaveBeenCalled();
  });
  it("loads last saved inactive settings after reopening, and explicitly saves before preparation", async () => {
    vi.mocked(prep.getPreparation).mockResolvedValue({
      ...READY,
      maps: { ...READY.maps, can_render: false, state: "needs_preparation" },
      renderer_settings: {
        marigold: {
          appearance: {
            lighting_source: "photo",
            lighting_strength: 0.7,
            fabric_texture: 0.4,
            print_shine: 0.2,
          },
          inference: { num_inference_steps: 12, ensemble_size: 5 },
        },
      },
    });
    const events: string[] = [];
    vi.mocked(calibrator.saveTemplateConfig).mockImplementation(async (_name, value) => {
      events.push("save");
      return value;
    });
    vi.spyOn(prep, "prepareTemplate").mockImplementation(async (request) => {
      events.push("prepare");
      expect(request.config_revision).toBe(READY.config_revision);
      return {
        id: "job",
        template: "tee",
        kind: "prepare",
        phase: "queued",
        step: "queued",
        elapsed: 0,
        placements_completed: 0,
        config_revision: "sha256:revision",
        placements_total: 1,
        error: null,
        last_event_sequence: 0,
        queue_position: 1,
        engine_version: null,
      };
    });
    render(<App />);
    await screen.findByLabelText("Renderer");
    await waitFor(() => expect(prep.getPreparation).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText("Renderer"), { target: { value: "marigold" } });
    expect(screen.getByLabelText("Fabric texture")).toHaveValue("40");
    const button = await screen.findByRole("button", { name: "Prepare template" });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() => expect(events).toEqual(["save", "prepare"]));
    expect(calibrator.saveTemplateConfig).toHaveBeenCalledWith(
      "tee",
      expect.objectContaining({ renderer: expect.objectContaining({ type: "marigold" }) }),
      [],
    );
  });
  it("refuses to enqueue when the revision save failed", async () => {
    vi.mocked(calibrator.saveTemplateConfig).mockRejectedValue(
      new Error("Template changed elsewhere. Reload before saving."),
    );
    const start = vi.spyOn(prep, "prepareTemplate");
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Renderer"), { target: { value: "marigold" } });
    const button = screen.getByRole("button", { name: "Prepare template" });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await screen.findByRole("alert");
    expect(start).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Template changed elsewhere");
    fireEvent.click(screen.getByRole("button", { name: "Reload template" }));
    await waitFor(() => expect(calibrator.getTemplateConfig).toHaveBeenCalledTimes(2));
  });
  it("does not invalidate unchanged advanced settings", async () => {
    vi.mocked(calibrator.getTemplateConfig).mockResolvedValue({
      config: SINGLE,
      modifiedAt: "Wed, 17 Sep 2026 18:30:00 GMT",
    });
    render(<App />);
    fireEvent.click(await screen.findByText("Advanced settings", { exact: false }));
    fireEvent.click(screen.getByText("Save settings"));
    await act(async () => {});
    expect(calibrator.saveTemplateConfig).not.toHaveBeenCalled();
  });
});

it("authorizes changed-photo mask recovery explicitly and preserves calibration edits", async () => {
  vi.mocked(calibrator.getTemplateConfig).mockResolvedValue({
    config: SINGLE,
    modifiedAt: "Wed, 17 Sep 2026 18:30:00 GMT",
  });
  vi.mocked(prep.getPreparation).mockResolvedValue({
    ...READY,
    maps: {
      ...READY.maps,
      state: "out_of_date",
      can_render: false,
      reason: "photo_changed",
      message: "The main photo changed.",
    },
    placements: [
      { placement_id: null, mask_available: false, mask_reason: "photo mismatch", undo_count: 0 },
    ],
  });
  const start = vi.spyOn(prep, "prepareTemplate").mockResolvedValue({
    id: "recovery",
    template: "tee",
    kind: "prepare",
    phase: "queued",
    step: "queued",
    elapsed: 0,
    placements_completed: 0,
    config_revision: "sha256:revision",
    placements_total: 1,
    error: null,
    last_event_sequence: 0,
    queue_position: 1,
    engine_version: null,
  });
  render(<App />);
  await screen.findByLabelText("Renderer");
  fireEvent.change(screen.getByLabelText("Fabric texture"), { target: { value: "51" } });
  const button = screen.getByRole("button", { name: "Reset masks and prepare" });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await waitFor(() =>
    expect(start).toHaveBeenCalledWith(
      expect.objectContaining({ action: "prepare_again", reset_masks_for_photo: true }),
    ),
  );
  expect(calibrator.saveTemplateConfig).toHaveBeenCalledWith(
    "tee",
    expect.objectContaining({
      renderer: expect.objectContaining({
        config: expect.objectContaining({
          appearance: expect.objectContaining({ fabric_texture: 0.51 }),
        }),
      }),
    }),
    [],
  );
});

it("shows loading while a saved template config is pending instead of kind assignment", async () => {
  let finish!: (value: Awaited<ReturnType<typeof calibrator.getTemplateConfig>>) => void;
  vi.mocked(calibrator.getTemplateConfig).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  render(<App />);
  await screen.findByText("Loading template...");
  expect(screen.queryByText(/Choose a template kind/)).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Renderer")).not.toBeInTheDocument();
  await act(async () =>
    finish({
      config: { ...SINGLE, renderer: PHOTOWARP },
      modifiedAt: "Wed, 17 Sep 2026 18:30:00 GMT",
    }),
  );
  expect(await screen.findByLabelText("Renderer")).toHaveValue("photo-warp");
});
