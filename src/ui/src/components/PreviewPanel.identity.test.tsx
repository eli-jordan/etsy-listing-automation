import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../api/calibrator";
import { PreviewPanel, type PreviewJob } from "./PreviewPanel";
import { BOX, MARIGOLD } from "../test/marigold";
const jobs: PreviewJob[] = [
  { id: "tee", label: "Tee", body: { bounding_box: BOX, renderer: MARIGOLD } },
];
afterEach(() => vi.restoreAllMocks());
beforeEach(() => vi.mocked(URL.revokeObjectURL).mockClear());
describe("PreviewPanel request identity", () => {
  it("rejects a late image for a changed design and keeps explicit rendering", async () => {
    let resolve!: (url: string) => void;
    const renderCall = vi.spyOn(calibrator, "renderPreview").mockImplementation(
      () =>
        new Promise((r) => {
          resolve = r;
        }),
    );
    const view = render(
      <PreviewPanel templateName="tee" jobs={jobs} design="a" active identity="maps1" />,
    );
    await waitFor(() => expect(renderCall).toHaveBeenCalledTimes(1));
    view.rerender(
      <PreviewPanel templateName="tee" jobs={jobs} design="b" active identity="maps1" />,
    );
    await act(async () => {
      resolve("blob:old");
    });
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:old");
    expect(screen.queryByAltText("Tee")).not.toBeInTheDocument();
    expect(screen.getByText("Re-render")).toHaveClass("btn-danger");
    expect(renderCall).toHaveBeenCalledTimes(1);
  });
  it("retains finished images while map generation changes and makes Re-render red", async () => {
    const call = vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:accepted");
    const view = render(
      <PreviewPanel templateName="tee" jobs={jobs} design="a" active identity="maps1" />,
    );
    await screen.findByAltText("Tee");
    view.rerender(
      <PreviewPanel templateName="tee" jobs={jobs} design="a" active identity="maps2" />,
    );
    expect(screen.getByAltText("Tee")).toHaveAttribute("src", "blob:accepted");
    expect(screen.getByText("Re-render")).toHaveClass("btn-danger");
    expect(call).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText("Re-render"));
    await waitFor(() => expect(call).toHaveBeenCalledTimes(2));
  });
});
