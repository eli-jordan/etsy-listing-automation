import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../api/calibrator";
import type { ColourMatrixTemplate } from "../types";
import { Gallery } from "./Gallery";

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

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("Gallery", () => {
  it("renders nothing for a single-colour set", () => {
    const { container } = render(
      <Gallery templateName="flat-lay-01" colours={["black"]} config={CONFIG} design="bundled-grid" />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("fetches one preview per colour, in parallel, after the debounce", async () => {
    const spy = vi
      .spyOn(calibrator, "renderPreview")
      .mockImplementation(async (_name, body) => `blob:${"colour" in body ? body.colour : ""}`);

    render(<Gallery templateName="flat-lay-01" colours={["black", "ivory"]} config={CONFIG} design="bundled-grid" />);

    expect(spy).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(800);
    vi.useRealTimers(); // waitFor's own polling needs a real clock to advance

    expect(spy).toHaveBeenCalledTimes(2);
    expect(spy).toHaveBeenCalledWith(
      "flat-lay-01",
      expect.objectContaining({ colour: "black", bounding_box: CONFIG.bounding_box }),
      "bundled-grid",
    );
    await waitFor(() => expect(screen.getByAltText("black")).toHaveAttribute("src", "blob:black"));
    expect(screen.getByAltText("ivory")).toHaveAttribute("src", "blob:ivory");
  });

  it("only fires once for rapid successive config changes (debounced)", async () => {
    const spy = vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:x");
    const { rerender } = render(
      <Gallery templateName="flat-lay-01" colours={["black", "ivory"]} config={CONFIG} design="bundled-grid" />,
    );
    const changed = { ...CONFIG, shade: { ...CONFIG.shade, opacity: 0.9 } };
    rerender(<Gallery templateName="flat-lay-01" colours={["black", "ivory"]} config={changed} design="bundled-grid" />);

    await vi.advanceTimersByTimeAsync(800);
    // Two colours, but only the latest config's debounce fired -- not one
    // batch per render.
    expect(spy).toHaveBeenCalledTimes(2);
  });
});
