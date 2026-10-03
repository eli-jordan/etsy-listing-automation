import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../api/calibrator";
import type { SingleTemplate } from "../types";
import { SingleEditor } from "./SingleEditor";

const SPACE: [number, number] = [400, 200];

const CONFIG: SingleTemplate = {
  kind: "single",
  colour: null,
  artwork: null,
  bounding_box: [
    { x: 0, y: 0 },
    { x: 100, y: 0 },
    { x: 100, y: 100 },
    { x: 0, y: 100 },
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

describe("SingleEditor", () => {
  it("fetches a preview with no colour selector and renders the box editor", async () => {
    const spy = vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    render(
      <SingleEditor
        templateName="lifestyle-01"
        config={CONFIG}
        space={SPACE}
        onChange={vi.fn()}
        design="bundled-grid"
        onDesignChange={vi.fn()}
      />,
    );

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        "lifestyle-01",
        {
          bounding_box: CONFIG.bounding_box,
          displace: CONFIG.displace,
          shade: CONFIG.shade,
        },
        "bundled-grid",
        "editor",
      ),
    );
    await screen.findByAltText("Rendered preview");
  });

  it("editing the colour field updates the config", async () => {
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    const onChange = vi.fn();
    render(
      <SingleEditor
        templateName="lifestyle-01"
        config={CONFIG}
        space={SPACE}
        onChange={onChange}
        design="bundled-grid"
        onDesignChange={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Garment colour (optional)"), {
      target: { value: "black" },
    });
    expect(onChange).toHaveBeenCalledWith({ ...CONFIG, colour: "black" });
  });

  /** One box, always selected: without this there was no way to get the
   * outline and its four handles off the artwork being judged. */
  it("hiding the placement outline leaves the render with no chrome", async () => {
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    const { container } = render(
      <SingleEditor
        templateName="lifestyle-01"
        config={CONFIG}
        space={SPACE}
        onChange={vi.fn()}
        design="bundled-grid"
        onDesignChange={vi.fn()}
      />,
    );

    const img = await screen.findByAltText("Rendered preview");
    Object.defineProperty(img, "naturalWidth", { value: 480, configurable: true });
    Object.defineProperty(img, "naturalHeight", { value: 576, configurable: true });
    fireEvent.load(img);
    expect(container.querySelectorAll(".quad-editor__box")).toHaveLength(1);

    fireEvent.click(screen.getByLabelText("show placement outline"));
    expect(container.querySelectorAll(".quad-editor__box")).toHaveLength(0);
    expect(container.querySelectorAll(".quad-editor__handle")).toHaveLength(0);
  });
});
