import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../api/calibrator";
import { UploadForm } from "./UploadForm";

afterEach(() => vi.restoreAllMocks());

describe("UploadForm", () => {
  it("says a name is needed rather than silently doing nothing", async () => {
    const spy = vi.spyOn(calibrator, "uploadTemplate");
    render(<UploadForm onUploaded={vi.fn()} />);
    const file = new File(["x"], "black.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Photos"), { target: { files: [file] } });
    expect(spy).not.toHaveBeenCalled();
    // It used to just `return`, which looks exactly like a broken upload.
    await screen.findByText("name the template first");
  });

  it("uploads under the name as it stands right now, not as it was last render", async () => {
    // handleFiles used to close over `name` from the render that attached it.
    // Type a name and pick files fast enough -- which automation always does --
    // and the handler still saw "", so the upload silently never happened.
    const spy = vi.spyOn(calibrator, "uploadTemplate").mockResolvedValue({
      name: "quick",
      kind: null,
      colours: [],
    });
    render(<UploadForm onUploaded={vi.fn()} />);

    const nameInput = screen.getByLabelText("Name");
    const fileInput = screen.getByLabelText("Photos");
    const file = new File(["x"], "black.png", { type: "image/png" });

    // Both events dispatched back to back, with no render flushed between.
    fireEvent.change(nameInput, { target: { value: "quick" } });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => expect(spy).toHaveBeenCalledWith("quick", [file]));
  });

  it("uploads with the chosen name and files, then reports success", async () => {
    const spy = vi.spyOn(calibrator, "uploadTemplate").mockResolvedValue({
      name: "flat-lay-02",
      kind: null,
      colours: [],
    });
    const onUploaded = vi.fn();
    render(<UploadForm onUploaded={onUploaded} />);

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "flat-lay-02" } });
    const file = new File(["x"], "black.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Photos"), { target: { files: [file] } });

    await waitFor(() => expect(spy).toHaveBeenCalledWith("flat-lay-02", [file]));
    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith("flat-lay-02"));
    await screen.findByText("uploaded");
  });

  it("always accepts several photos, since the kind is not known yet", () => {
    // Kind used to gate this (one file for a scene, many for a colour set),
    // but it is asked afterwards now -- so the input cannot narrow itself.
    render(<UploadForm onUploaded={vi.fn()} />);
    expect((screen.getByLabelText("Photos") as HTMLInputElement).multiple).toBe(true);
    expect(screen.queryByLabelText("Kind")).not.toBeInTheDocument();
  });

  it("reports a failure status when the upload rejects", async () => {
    vi.spyOn(calibrator, "uploadTemplate").mockRejectedValue(new Error("nope"));
    render(<UploadForm onUploaded={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "x" } });
    fireEvent.change(screen.getByLabelText("Photos"), {
      target: { files: [new File(["x"], "a.png")] },
    });
    await screen.findByText("upload failed");
  });
});
