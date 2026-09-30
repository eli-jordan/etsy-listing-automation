import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../api/calibrator";
import { PreviewPanel, type PreviewJob } from "./PreviewPanel";

const BOX: PreviewJob["body"] = {
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

function colourJobs(jobs = COLOURS): PreviewJob[] {
  return jobs.map((colour) => ({ id: colour, label: colour, body: { colour, ...BOX } }));
}

const SINGLE: PreviewJob[] = [{ id: "lifestyle-01", label: "lifestyle-01", body: BOX }];

function setup(
  jobs: PreviewJob[] = colourJobs(),
  props: Partial<Parameters<typeof PreviewPanel>[0]> = {},
) {
  return render(
    <PreviewPanel templateName="flat-lay-01" jobs={jobs} design="bundled-grid" active {...props} />,
  );
}

const rerenderButton = () => screen.getByRole("button", { name: "Re-render" });

beforeEach(() => {
  vi.mocked(URL.revokeObjectURL).mockClear();
});

afterEach(() => vi.restoreAllMocks());

describe("PreviewPanel", () => {
  it("renders nothing while the tab is behind the canvas", async () => {
    const spy = vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:one");
    setup(colourJobs(), { active: false });

    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(spy).not.toHaveBeenCalled();
  });

  it("renders the set the first time the tab comes forward", async () => {
    const spy = vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:one");
    const { rerender } = setup(colourJobs(), { active: false });
    expect(spy).not.toHaveBeenCalled();

    rerender(
      <PreviewPanel templateName="flat-lay-01" jobs={colourJobs()} design="bundled-grid" active />,
    );
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(3));
  });

  it("does not start the set again when the tab is left and returned to", async () => {
    const spy = vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:one");
    const { rerender } = setup();
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(3));

    const show = (active: boolean) =>
      rerender(
        <PreviewPanel
          templateName="flat-lay-01"
          jobs={colourJobs()}
          design="bundled-grid"
          active={active}
        />,
      );
    show(false);
    show(true);

    await new Promise((resolve) => setTimeout(resolve, 100));
    // Three renders, not six: the panel stays mounted behind the canvas, so
    // flicking between tabs shows what was rendered rather than spending the
    // set again.
    expect(spy).toHaveBeenCalledTimes(3);
  });

  it("renders every job at full size, one at a time, and counts them", async () => {
    const spy = vi
      .spyOn(calibrator, "renderPreview")
      .mockImplementation(async (_name, body) => `blob:${(body as { colour: string }).colour}`);
    setup();

    await waitFor(() => expect(screen.getByText("3 / 3")).toBeInTheDocument());
    expect(spy).toHaveBeenCalledTimes(3);
    for (const colour of COLOURS) {
      expect(spy).toHaveBeenCalledWith(
        "flat-lay-01",
        expect.objectContaining({ colour }),
        "bundled-grid",
        "full",
      );
    }
    expect(screen.getByAltText("moss")).toHaveAttribute("src", "blob:moss");
  });

  it("a failed job costs that tile, not the tab", async () => {
    vi.spyOn(calibrator, "renderPreview")
      .mockResolvedValueOnce("blob:black")
      .mockRejectedValueOnce(new Error("no photo"))
      .mockResolvedValueOnce("blob:moss");
    setup();

    expect(await screen.findByText("1 preview failed to render")).toBeInTheDocument();
    expect(screen.getByText("2 / 3")).toBeInTheDocument();
    expect(screen.getByAltText("moss")).toBeInTheDocument();
  });

  it("turns Re-render red when the boxes have moved, rather than re-running", async () => {
    const spy = vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:one");
    const { rerender } = setup(SINGLE);
    await waitFor(() => expect(screen.getByText("1 / 1")).toBeInTheDocument());
    expect(rerenderButton()).not.toHaveClass("btn-danger");
    spy.mockClear();

    const moved: PreviewJob[] = [
      {
        id: "lifestyle-01",
        label: "lifestyle-01",
        body: {
          ...BOX,
          bounding_box: [
            { x: 5, y: 5 },
            { x: 105, y: 5 },
            { x: 105, y: 105 },
            { x: 5, y: 105 },
          ],
        },
      },
    ];
    rerender(<PreviewPanel templateName="flat-lay-01" jobs={moved} design="bundled-grid" active />);

    // The state worth interrupting for -- what is on screen is not what you
    // would be approving -- said with the button rather than a line of prose
    // beside the count.
    expect(rerenderButton()).toHaveClass("btn-danger");
    // And a nudge still does not silently re-render.
    expect(spy).not.toHaveBeenCalled();
  });

  it("re-rendering revokes the blobs the previous run made", async () => {
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:one");
    setup(SINGLE);
    await waitFor(() => expect(screen.getByText("1 / 1")).toBeInTheDocument());
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();

    fireEvent.click(rerenderButton());
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:one");
  });

  it("revokes everything on the way out", async () => {
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:one");
    const { unmount } = setup(SINGLE);
    await waitFor(() => expect(screen.getByText("1 / 1")).toBeInTheDocument());

    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:one");
  });

  it("clicking a tile opens it large, and Escape closes it", async () => {
    vi.spyOn(calibrator, "renderPreview").mockImplementation(
      async (_name, body) => `blob:${(body as { colour: string }).colour}`,
    );
    setup();
    await waitFor(() => expect(screen.getByText("3 / 3")).toBeInTheDocument());

    fireEvent.click(screen.getByAltText("ivory").closest("button") as HTMLElement);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAccessibleName("ivory, preview 2 of 3");

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("offers the approve action only when the caller has one", async () => {
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:one");
    const onApprove = vi.fn();
    const { unmount } = setup(colourJobs(), { onApprove });
    fireEvent.click(screen.getByRole("button", { name: /approve/i }));
    expect(onApprove).toHaveBeenCalled();
    unmount();

    setup(SINGLE);
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
  });
});
