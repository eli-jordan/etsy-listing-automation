import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

function summary(over: Partial<TemplateSummary> & { name: string }): TemplateSummary {
  return {
    kind: "colour-matrix",
    colours: ["black", "moss"],
    has_config: true,
    status: "calibrated",
    status_reason: null,
    ...over,
  };
}

/** Picks a template the way the user does now -- by clicking its rail row. */
function selectTemplate(name: string): void {
  fireEvent.click(screen.getByRole("button", { name: new RegExp(name) }));
}

/** The header repeats what the rail row already says, so header assertions
 * have to be scoped or they match twice. */
function header() {
  return within(screen.getByRole("banner"));
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("App", () => {
  it("loads templates and renders the colour-matrix editor for the selected one", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([summary({ name: "flat-lay-01" })]);
    vi.spyOn(calibrator, "getTemplateConfig").mockResolvedValue(COLOUR_MATRIX);
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");

    render(<App />);

    await waitFor(() => expect(screen.getByText("Loading preview…")).toBeInTheDocument());
  });

  it("names the open template in the header, beside the title", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([summary({ name: "flat-lay-01" })]);
    vi.spyOn(calibrator, "getTemplateConfig").mockResolvedValue(COLOUR_MATRIX);
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");

    render(<App />);
    await waitFor(() => expect(header().getByText("flat-lay-01")).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Mockup calibrator" })).toBeInTheDocument();
  });

  it("shows the open template's calibration state and contents in the header", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([
      summary({ name: "tote", kind: "multiple", colours: [], status_reason: null }),
    ]);
    vi.spyOn(calibrator, "getTemplateConfig").mockResolvedValue(MULTIPLE);
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");

    render(<App />);
    await waitFor(() => expect(header().getByText("calibrated")).toBeInTheDocument());
    expect(header().getByText("Multiple · 0 colours")).toBeInTheDocument();
  });

  it("shows why an unfinished template is unfinished, in the header", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([
      summary({
        name: "tote",
        kind: "multiple",
        colours: [],
        status: "needs-calibration",
        status_reason: "no boxes",
      }),
    ]);
    vi.spyOn(calibrator, "getTemplateConfig").mockResolvedValue(MULTIPLE);
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");

    render(<App />);
    await waitFor(() => expect(header().getByText("no boxes")).toBeInTheDocument());
  });

  it("switches editor when a multiple-kind template is picked from the rail", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([
      summary({ name: "flat-lay-01" }),
      summary({ name: "colour-chart-01", kind: "multiple", colours: [] }),
    ]);
    vi.spyOn(calibrator, "getTemplateConfig").mockImplementation(async (name) =>
      name === "colour-chart-01" ? MULTIPLE : COLOUR_MATRIX,
    );
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");

    render(<App />);
    await screen.findByText("Loading preview…");

    selectTemplate("colour-chart-01");
    await waitFor(() => expect(screen.getByText("Placements")).toBeInTheDocument());
  });

  it("shows a message when a template has no config yet", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([
      summary({
        name: "brand-new",
        kind: null,
        colours: [],
        has_config: false,
        status: "needs-calibration",
        status_reason: "no kind set",
      }),
    ]);
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
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([summary({ name: "flat-lay-01" })]);
    vi.spyOn(calibrator, "getTemplateConfig").mockResolvedValue(COLOUR_MATRIX);
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    const saveSpy = vi.spyOn(calibrator, "saveTemplateConfig").mockResolvedValue(COLOUR_MATRIX);

    render(<App />);
    await waitFor(() => expect(screen.getByRole("button", { name: /Save/ })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /Save/ }));

    await waitFor(() => expect(saveSpy).toHaveBeenCalledWith("flat-lay-01", COLOUR_MATRIX));
    await waitFor(() => expect(screen.getByText("saved")).toBeInTheDocument());
  });

  describe("Reset", () => {
    async function renderWithEdit() {
      vi.spyOn(calibrator, "listTemplates").mockResolvedValue([summary({ name: "flat-lay-01" })]);
      vi.spyOn(calibrator, "getTemplateConfig").mockResolvedValue(COLOUR_MATRIX);
      vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
      render(<App />);

      const strength = await screen.findByLabelText(/strength/);
      fireEvent.change(strength, { target: { value: "0.75" } });
      await waitFor(() => expect(strength).toHaveValue("0.75"));
      return strength;
    }

    it("is disabled until something is edited", async () => {
      vi.spyOn(calibrator, "listTemplates").mockResolvedValue([summary({ name: "flat-lay-01" })]);
      vi.spyOn(calibrator, "getTemplateConfig").mockResolvedValue(COLOUR_MATRIX);
      vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
      render(<App />);
      await screen.findByLabelText(/strength/);
      expect(screen.getByRole("button", { name: "Reset" })).toBeDisabled();
    });

    it("throws away unsaved edits and goes back to what is on disk", async () => {
      const strength = await renderWithEdit();
      fireEvent.click(screen.getByRole("button", { name: "Reset" }));
      await waitFor(() => expect(strength).toHaveValue("0"));
    });

    it("does not re-fetch to do it -- the last saved config is already held", async () => {
      const getSpy = vi.spyOn(calibrator, "getTemplateConfig");
      await renderWithEdit();
      const callsBefore = getSpy.mock.calls.length;
      fireEvent.click(screen.getByRole("button", { name: "Reset" }));
      await waitFor(() => expect(getSpy.mock.calls.length).toBe(callsBefore));
    });
  });
});
