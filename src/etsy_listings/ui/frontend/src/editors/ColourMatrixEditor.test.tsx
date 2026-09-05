import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../api/calibrator";
import type { ColourMatrixTemplate } from "../types";
import { ColourMatrixEditor } from "./ColourMatrixEditor";

const CONFIG: ColourMatrixTemplate = {
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

const COLOURS = ["black", "ivory", "moss"];

type Props = Parameters<typeof ColourMatrixEditor>[0];

function setup(props: Partial<Props> = {}) {
  const onChange = vi.fn();
  const onApprove = vi.fn();
  const full: Props = {
    templateName: "flat-lay-01",
    config: CONFIG,
    colours: COLOURS,
    onChange,
    design: "bundled-grid",
    onDesignChange: vi.fn(),
    onApprove,
    ...props,
  };
  const view = render(<ColourMatrixEditor {...full} />);
  return {
    onChange,
    onApprove,
    /** Re-render with some props changed -- for the colour list moving
     * underneath the editor. */
    update: (next: Partial<Props>) =>
      view.rerender(<ColourMatrixEditor {...full} {...next} />),
  };
}

afterEach(() => vi.restoreAllMocks());

beforeEach(() => {
  // The inspector carries the test-design picker, which fetches the library on
  // mount. Stubbed so these tests stay about the editor.
  vi.spyOn(calibrator, "listDesigns").mockResolvedValue([]);
});

describe("ColourMatrixEditor", () => {
  it("previews the first colour until another is picked", async () => {
    const spy = vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    setup();

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        "flat-lay-01",
        {
          colour: "black",
          bounding_box: CONFIG.bounding_box,
          displace: CONFIG.displace,
          shade: CONFIG.shade,
        },
        "bundled-grid",
      ),
    );
    await screen.findByAltText("Rendered preview");
  });

  it("picking a colour from the filmstrip re-previews that colour", async () => {
    const spy = vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    setup();
    await waitFor(() => expect(spy).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "moss" }));

    await waitFor(() =>
      expect(spy).toHaveBeenLastCalledWith(
        "flat-lay-01",
        expect.objectContaining({ colour: "moss" }),
        "bundled-grid",
      ),
    );
  });

  it("falls back to the first colour when the selected one leaves the set", async () => {
    /* The selection is derived, not synced through an effect: a colour list
     * that changed underneath (a photo was deleted) must not leave the editor
     * previewing a colour that no longer has one. */
    const spy = vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    const { update } = setup();
    await waitFor(() => expect(spy).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "moss" }));
    await waitFor(() =>
      expect(spy).toHaveBeenLastCalledWith(
        "flat-lay-01",
        expect.objectContaining({ colour: "moss" }),
        "bundled-grid",
      ),
    );

    update({ colours: ["black", "ivory"] });
    await waitFor(() =>
      expect(spy).toHaveBeenLastCalledWith(
        "flat-lay-01",
        expect.objectContaining({ colour: "black" }),
        "bundled-grid",
      ),
    );
  });

  it("shows no filmstrip for a single-colour set", async () => {
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    setup({ colours: ["black"] });
    await screen.findByAltText("Rendered preview");

    expect(screen.queryByRole("button", { name: "black" })).not.toBeInTheDocument();
  });

  it("asks for no preview at all when the set has no colours", async () => {
    const spy = vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    setup({ colours: [] });

    await new Promise((resolve) => setTimeout(resolve, 250));
    expect(spy).not.toHaveBeenCalled();
    expect(screen.getByText("Loading preview…")).toBeInTheDocument();
  });

  it("switching to Preview all hides the outline toggle and renders the grid", async () => {
    const spy = vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    setup();
    await screen.findByAltText("Rendered preview");
    expect(screen.getByLabelText("show placement outline")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Preview all 3" }));

    expect(screen.queryByLabelText("show placement outline")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(spy).toHaveBeenLastCalledWith(
        "flat-lay-01",
        expect.objectContaining({ colour: "moss" }),
        "bundled-grid",
      ),
    );
  });

  it("approving from the Preview all tab saves", async () => {
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    const { onApprove } = setup();
    await screen.findByAltText("Rendered preview");

    fireEvent.click(screen.getByRole("tab", { name: "Preview all 3" }));
    const approve = await screen.findByRole("button", { name: /approve/i });
    fireEvent.click(approve);

    expect(onApprove).toHaveBeenCalled();
  });

  it("the outline toggle switches the box overlay off", async () => {
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    setup();
    await screen.findByAltText("Rendered preview");

    const toggle = screen.getByLabelText("show placement outline");
    expect(toggle).toBeChecked();
    fireEvent.click(toggle);
    expect(toggle).not.toBeChecked();
  });

  it("a print-realism change is reported against the whole config", async () => {
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    const { onChange } = setup();
    await screen.findByAltText("Rendered preview");

    fireEvent.click(screen.getByLabelText("Follow fabric wrinkles"));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "colour-matrix",
        displace: expect.objectContaining({ enabled: true }),
      }),
    );
  });
});
