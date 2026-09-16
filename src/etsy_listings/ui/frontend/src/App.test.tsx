import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
    photos: [],
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

beforeEach(() => {
  // Every editor's inspector mounts the test-design picker, which fetches the
  // library. Stubbed so these tests stay about App's own behaviour.
  vi.spyOn(calibrator, "listDesigns").mockResolvedValue([]);
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
    // "show all outlines" is the multiple editor's toggle, and only its own --
    // a colour set says "show placement outline".
    await waitFor(() => expect(screen.getByText("show all outlines")).toBeInTheDocument());
  });

  it("replaces the workspace with the kind picker when a template has no config", async () => {
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
    vi.spyOn(calibrator, "getColourReport").mockResolvedValue([]);

    render(<App />);
    await waitFor(() =>
      expect(screen.getByText("What kind of template is this?")).toBeInTheDocument(),
    );
    // A takeover, not a panel: nothing else may be touched until it is answered.
    expect(screen.queryByLabelText("Test design")).not.toBeInTheDocument();
  });

  it("says where templates come from when there are none", async () => {
    // The calibrator no longer creates them: a template is a folder in the
    // workspace, so the empty state points at the workspace.
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([]);
    render(<App />);
    await waitFor(() =>
      expect(screen.getByText(/add a folder of photos under mockup-templates/)).toBeInTheDocument(),
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

  describe("racing refreshes", () => {
    it("ignores a template list that arrives after a newer one", async () => {
      // Assigning a kind and then saving fires two listTemplates() calls in
      // quick succession. If the first resolves last -- entirely possible, they
      // are separate requests -- it puts the pre-assignment list back, and the
      // template silently reverts to "no kind set" in the UI while the file on
      // disk says otherwise. Under load this is what made the browser tests
      // intermittent.
      const initial = [summary({ name: "fresh", colours: ["black"] })];
      const stale = [summary({ name: "fresh", colours: ["black"] })];
      const newest = [summary({ name: "fresh", colours: ["black", "ivory", "moss"] })];

      let resolveStale: (v: TemplateSummary[]) => void = () => {};
      const pending = new Promise<TemplateSummary[]>((r) => (resolveStale = r));
      vi.spyOn(calibrator, "listTemplates")
        .mockResolvedValueOnce(initial) // mount
        .mockReturnValueOnce(pending) // first save: in flight, resolves last
        .mockResolvedValue(newest); // second save: lands first, and wins
      vi.spyOn(calibrator, "getTemplateConfig").mockResolvedValue(COLOUR_MATRIX);
      vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
      vi.spyOn(calibrator, "saveTemplateConfig").mockResolvedValue(COLOUR_MATRIX);

      render(<App />);
      const save = await screen.findByRole("button", { name: "Save template.yaml" });
      await waitFor(() => expect(save).toBeEnabled());

      fireEvent.click(save); // refresh #2 -- hangs
      fireEvent.click(save); // refresh #3 -- resolves now
      await waitFor(() => expect(header().getByText(/3 colours/)).toBeInTheDocument());

      // The older refresh finally lands. It must be discarded, not applied.
      // `act` so React actually flushes the stale response's state update --
      // a bare microtask tick would let this pass without the guard.
      resolveStale(stale);
      await act(async () => {
        await new Promise((r) => setTimeout(r, 10));
      });
      expect(header().getByText(/3 colours/)).toBeInTheDocument();
    });
  });

  describe("Reset", () => {
    /** Reset is the header's, but the only way to make the page dirty is
     * through a real control -- so this drives the wrinkle slider, which the
     * Print realism panel exposes as a 0-100 percentage over a 0..1 config. */
    async function mount() {
      vi.spyOn(calibrator, "listTemplates").mockResolvedValue([summary({ name: "flat-lay-01" })]);
      vi.spyOn(calibrator, "getTemplateConfig").mockResolvedValue(COLOUR_MATRIX);
      vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
      render(<App />);
      return await screen.findByLabelText("Wrinkle strength");
    }

    async function mountAndEdit() {
      const strength = await mount();
      fireEvent.change(strength, { target: { value: "75" } });
      await waitFor(() => expect(strength).toHaveValue("75"));
      return strength;
    }

    it("is disabled until something is edited", async () => {
      await mount();
      expect(screen.getByRole("button", { name: "Reset" })).toBeDisabled();
    });

    it("throws away unsaved edits and goes back to what is on disk", async () => {
      const strength = await mountAndEdit();
      fireEvent.click(screen.getByRole("button", { name: "Reset" }));
      await waitFor(() => expect(strength).toHaveValue("0"));
    });

    it("does not re-fetch to do it -- the last saved config is already held", async () => {
      const getSpy = vi.spyOn(calibrator, "getTemplateConfig");
      await mountAndEdit();
      const callsBefore = getSpy.mock.calls.length;
      fireEvent.click(screen.getByRole("button", { name: "Reset" }));
      await waitFor(() => expect(getSpy.mock.calls.length).toBe(callsBefore));
    });
  });
});
