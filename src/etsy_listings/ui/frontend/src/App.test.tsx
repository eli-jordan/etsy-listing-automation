import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import * as calibrator from "./api/calibrator";
import type { ColourMatrixTemplate, MultipleTemplate, TemplateSummary } from "./types";

const COLOUR_MATRIX: ColourMatrixTemplate = {
  kind: "colour-matrix",
  bounding_box: [
    { x: 0, y: 0 },
    { x: 100, y: 0 },
    { x: 100, y: 100 },
    { x: 0, y: 100 },
  ],
  displace: { enabled: false, strength: 0 },
  shade: { enabled: true, opacity: 0.6, blend: "soft-light" },
};

const MULTIPLE: MultipleTemplate = {
  kind: "multiple",
  colour_coverage: "exact",
  placements: [],
  displace: { enabled: false, strength: 0 },
  shade: { enabled: true, opacity: 0.6, blend: "soft-light" },
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("App", () => {
  it("loads templates and renders the colour-matrix editor for the selected one", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([
      { name: "flat-lay-01", kind: "colour-matrix", colours: ["black", "moss"], has_config: true },
    ] satisfies TemplateSummary[]);
    vi.spyOn(calibrator, "getTemplateConfig").mockResolvedValue(COLOUR_MATRIX);
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");

    render(<App />);

    await waitFor(() => expect(screen.getByText("Loading preview…")).toBeInTheDocument());
    expect(screen.getByLabelText("Template")).toHaveValue("flat-lay-01");
  });

  it("switches editor when a multiple-kind template is selected", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([
      { name: "flat-lay-01", kind: "colour-matrix", colours: ["black"], has_config: true },
      { name: "colour-chart-01", kind: "multiple", colours: [], has_config: true },
    ] satisfies TemplateSummary[]);
    vi.spyOn(calibrator, "getTemplateConfig").mockImplementation(async (name) =>
      name === "colour-chart-01" ? MULTIPLE : COLOUR_MATRIX,
    );
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText("Template")).toHaveValue("flat-lay-01"));

    fireEvent.change(screen.getByLabelText("Template"), { target: { value: "colour-chart-01" } });
    await waitFor(() => expect(screen.getByText("Placements")).toBeInTheDocument());
  });

  it("shows a message when a template has no config yet", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([
      { name: "brand-new", kind: null, colours: [], has_config: false },
    ] satisfies TemplateSummary[]);
    vi.spyOn(calibrator, "getTemplateConfig").mockResolvedValue(null);

    render(<App />);
    await waitFor(() =>
      expect(screen.getByText("No template.yaml yet for brand-new.")).toBeInTheDocument(),
    );
  });

  it("shows a prompt to upload when there are no templates", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([]);
    render(<App />);
    await waitFor(() =>
      expect(screen.getByText("No templates yet -- upload one below.")).toBeInTheDocument(),
    );
  });

  it("reports a status message when the template list fails to load", async () => {
    vi.spyOn(calibrator, "listTemplates").mockRejectedValue(new Error("network"));
    render(<App />);
    await waitFor(() => expect(screen.getByText("failed to load templates")).toBeInTheDocument());
  });

  it("save button writes the current config and reports success", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([
      { name: "flat-lay-01", kind: "colour-matrix", colours: ["black"], has_config: true },
    ] satisfies TemplateSummary[]);
    vi.spyOn(calibrator, "getTemplateConfig").mockResolvedValue(COLOUR_MATRIX);
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    const saveSpy = vi.spyOn(calibrator, "saveTemplateConfig").mockResolvedValue(COLOUR_MATRIX);

    render(<App />);
    await waitFor(() => expect(screen.getByRole("button", { name: /Save/ })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /Save/ }));

    await waitFor(() => expect(saveSpy).toHaveBeenCalledWith("flat-lay-01", COLOUR_MATRIX));
    await waitFor(() => expect(screen.getByText("saved")).toBeInTheDocument());
  });
});
