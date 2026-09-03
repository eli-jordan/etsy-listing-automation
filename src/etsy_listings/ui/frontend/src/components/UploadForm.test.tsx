import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../api/calibrator";
import { UploadForm } from "./UploadForm";

afterEach(() => vi.restoreAllMocks());

describe("UploadForm", () => {
  it("does nothing if no name has been entered", async () => {
    const spy = vi.spyOn(calibrator, "uploadTemplate");
    render(<UploadForm onUploaded={vi.fn()} />);
    const file = new File(["x"], "black.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText(/Photos/), { target: { files: [file] } });
    expect(spy).not.toHaveBeenCalled();
  });

  it("uploads with the chosen name, kind and files, then reports success", async () => {
    const spy = vi.spyOn(calibrator, "uploadTemplate").mockResolvedValue({
      name: "flat-lay-02",
      kind: "colour-matrix",
      colours: ["black"],
    });
    const onUploaded = vi.fn();
    render(<UploadForm onUploaded={onUploaded} />);

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "flat-lay-02" } });
    const file = new File(["x"], "black.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText(/Photos/), { target: { files: [file] } });

    await waitFor(() => expect(spy).toHaveBeenCalledWith("flat-lay-02", "colour-matrix", [file]));
    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith("flat-lay-02"));
    await screen.findByText("uploaded");
  });

  it("switches to a single-file input for multiple/single kind", () => {
    render(<UploadForm onUploaded={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "single" } });
    const input = screen.getByLabelText("Photo") as HTMLInputElement;
    expect(input.multiple).toBe(false);
  });

  it("reports a failure status when the upload rejects", async () => {
    vi.spyOn(calibrator, "uploadTemplate").mockRejectedValue(new Error("nope"));
    render(<UploadForm onUploaded={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "x" } });
    fireEvent.change(screen.getByLabelText(/Photos/), {
      target: { files: [new File(["x"], "a.png")] },
    });
    await screen.findByText("upload failed");
  });
});
