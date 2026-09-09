import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../api/calibrator";
import type { SingleTemplate } from "../types";
import { EditorShell } from "./EditorShell";

/** The chrome every kind shares, tested once against a stub canvas.
 *
 * These assertions used to live in the colour-matrix editor's file, because
 * that is where the controls happened to be written first -- so "does the
 * Preview tab hide the calibration controls?" was answered for one kind and
 * assumed for the other two. Driving the shell directly is what makes the
 * answer cover all three, and it needs no template kind at all to do it.
 */

const CONFIG: SingleTemplate = {
  kind: "single",
  colour: null,
  artwork: null,
  bounding_box: [
    { x: 0, y: 0 },
    { x: 10, y: 0 },
    { x: 10, y: 10 },
    { x: 0, y: 10 },
  ],
  displace: { enabled: false, strength: 0 },
  shade: { enabled: true, opacity: 0.6, blend: "soft-light" },
};

afterEach(() => vi.restoreAllMocks());

beforeEach(() => {
  // The inspector carries the test-design picker, which fetches the library
  // on mount. Stubbed so these tests stay about the shell.
  vi.spyOn(calibrator, "listDesigns").mockResolvedValue([]);
});

function setup(overrides: Partial<Parameters<typeof EditorShell<SingleTemplate>>[0]> = {}) {
  const onChange = vi.fn();
  render(
    <EditorShell
      templateName="lifestyle-01"
      config={CONFIG}
      onChange={onChange}
      design="bundled-grid"
      onDesignChange={vi.fn()}
      space={[400, 200]}
      previewUrl="blob:preview"
      jobs={[]}
      canvas={({ showOutlines }) => (
        <div data-testid="canvas">{showOutlines ? "outlined" : "bare"}</div>
      )}
      {...overrides}
    />,
  );
  return { onChange };
}

describe("EditorShell", () => {
  it("draws the canvas with outlines on, and lets them be switched off", () => {
    setup();

    expect(screen.getByTestId("canvas")).toHaveTextContent("outlined");
    const toggle = screen.getByLabelText("show placement outline");
    expect(toggle).toBeChecked();

    fireEvent.click(toggle);

    expect(toggle).not.toBeChecked();
    expect(screen.getByTestId("canvas")).toHaveTextContent("bare");
  });

  it("takes the outline label from the kind, since one box reads differently", () => {
    setup({ outlineLabel: "show all outlines" });

    expect(screen.getByLabelText("show all outlines")).toBeInTheDocument();
  });

  it("switching to Preview hides the calibration controls", () => {
    setup();
    expect(screen.getByTestId("canvas")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Preview" }));

    expect(screen.queryByTestId("canvas")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("show placement outline")).not.toBeInTheDocument();
  });

  it("holds the canvas back until there is both an image and a space to draw it in", () => {
    setup({ previewUrl: null });
    expect(screen.getByText("Loading preview…")).toBeInTheDocument();
    expect(screen.queryByTestId("canvas")).not.toBeInTheDocument();
  });

  it("holds it back for a photo whose pixel size could not be read", () => {
    /* A box saved against a guessed space is saved wrong, so there is nothing
       useful to show -- see `QuadEditor`'s `space`. */
    setup({ space: null });
    expect(screen.getByText("Loading preview…")).toBeInTheDocument();
  });

  it("reports a print-realism change against the whole config", () => {
    const { onChange } = setup();

    fireEvent.click(screen.getByLabelText("Follow fabric wrinkles"));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "single",
        displace: expect.objectContaining({ enabled: true }),
      }),
    );
  });

  it("shows a kind's extra bar and inspector controls, the bar only while calibrating", () => {
    setup({
      barExtras: <span data-testid="bar-extra">colour</span>,
      controls: <span data-testid="inspector-extra">garment colour</span>,
      footer: <p data-testid="footer">2 boxes have no colour</p>,
    });

    expect(screen.getByTestId("bar-extra")).toBeInTheDocument();
    expect(screen.getByTestId("inspector-extra")).toBeInTheDocument();
    expect(screen.getByTestId("footer")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Preview" }));

    // The inspector stays: it is what you adjust *with*, whichever view you
    // are judging in. The bar's extras and the canvas footer describe the
    // canvas, which is gone.
    expect(screen.queryByTestId("bar-extra")).not.toBeInTheDocument();
    expect(screen.queryByTestId("footer")).not.toBeInTheDocument();
    expect(screen.getByTestId("inspector-extra")).toBeInTheDocument();
  });
});
