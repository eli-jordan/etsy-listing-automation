import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../api/calibrator";
import type { ColourMatrixTemplate } from "../types";
import { PreviewGrid } from "./PreviewGrid";

const CONFIG: ColourMatrixTemplate = {
  kind: "colour-matrix",
  bounding_box: [
    { x: 0, y: 0 },
    { x: 10, y: 0 },
    { x: 10, y: 10 },
    { x: 0, y: 10 },
  ],
  displace: { enabled: false, strength: 0 },
  shade: { enabled: true, opacity: 0.6, blend: "soft-light" },
};

const COLOURS = ["sand", "black", "navy"];

afterEach(() => vi.restoreAllMocks());

function renderGrid(over: Partial<Parameters<typeof PreviewGrid>[0]> = {}) {
  const onApprove = vi.fn();
  render(
    <PreviewGrid
      templateName="heather-tee"
      colours={COLOURS}
      config={CONFIG}
      design="bundled-grid"
      onApprove={onApprove}
      {...over}
    />,
  );
  return { onApprove };
}

describe("PreviewGrid", () => {
  it("renders every colour through the real preview endpoint", async () => {
    const spy = vi
      .spyOn(calibrator, "renderPreview")
      .mockImplementation(async (_n, body) => `blob:${"colour" in body ? body.colour : "?"}`);
    renderGrid();

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(screen.getByAltText("sand")).toHaveAttribute("src", "blob:sand"));
    expect(screen.getByAltText("navy")).toHaveAttribute("src", "blob:navy");
  });

  it("renders one at a time rather than firing N at once", async () => {
    // The whole point of the tab is looking at a finished set; issuing every
    // render in parallel just makes the *first* one arrive later.
    let inFlight = 0;
    let peak = 0;
    vi.spyOn(calibrator, "renderPreview").mockImplementation(async () => {
      inFlight += 1;
      peak = Math.max(peak, inFlight);
      await new Promise((r) => setTimeout(r, 5));
      inFlight -= 1;
      return "blob:x";
    });

    renderGrid();
    await waitFor(() => expect(screen.getByText("3 / 3")).toBeInTheDocument());
    expect(peak).toBe(1);
  });

  it("counts progress as the renders land", async () => {
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:x");
    renderGrid();
    await waitFor(() => expect(screen.getByText("3 / 3")).toBeInTheDocument());
  });

  it("says it is still working until the last one lands", async () => {
    let release: (v: string) => void = () => {};
    const pending = new Promise<string>((r) => (release = r));
    vi.spyOn(calibrator, "renderPreview")
      .mockResolvedValueOnce("blob:1")
      .mockReturnValueOnce(pending)
      .mockResolvedValue("blob:3");

    renderGrid();
    await screen.findByText("rendering the rest…");
    release("blob:2");
    await waitFor(() => expect(screen.queryByText("rendering the rest…")).not.toBeInTheDocument());
  });

  it("offers approval, which is a save and not a new stored flag", async () => {
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:x");
    const { onApprove } = renderGrid();
    fireEvent.click(await screen.findByRole("button", { name: /Approve/ }));
    expect(onApprove).toHaveBeenCalled();
  });

  it("keeps going when one colour fails to render", async () => {
    // One bad photo should cost you that tile, not the whole tab.
    vi.spyOn(calibrator, "renderPreview")
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValue("blob:x");
    renderGrid();
    await waitFor(() => expect(screen.getByText("2 / 3")).toBeInTheDocument());
    expect(screen.getByText(/1 colour failed/)).toBeInTheDocument();
  });
});
