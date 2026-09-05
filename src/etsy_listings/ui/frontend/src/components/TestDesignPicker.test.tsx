import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../api/calibrator";
import type { DesignSummary } from "../types";
import { TestDesignPicker } from "./TestDesignPicker";

const BUNDLED: DesignSummary[] = [
  { id: "bundled-grid", label: "Grid / ruler target", source: "bundled" },
  { id: "bundled-on-light", label: "Sample art · light ink", source: "bundled" },
  { id: "bundled-on-dark", label: "Sample art · dark ink", source: "bundled" },
];

afterEach(() => vi.restoreAllMocks());

function renderPicker(designs = BUNDLED, value = "bundled-grid") {
  vi.spyOn(calibrator, "listDesigns").mockResolvedValue(designs);
  const onChange = vi.fn();
  render(<TestDesignPicker value={value} onChange={onChange} />);
  return { onChange };
}

describe("TestDesignPicker", () => {
  it("offers every design in the library, by label", async () => {
    renderPicker();
    const select = await screen.findByLabelText("Test design");
    expect([...select.querySelectorAll("option")].map((o) => o.textContent)).toEqual([
      "Grid / ruler target",
      "Sample art · light ink",
      "Sample art · dark ink",
    ]);
  });

  it("reflects the current selection", async () => {
    renderPicker(BUNDLED, "bundled-on-dark");
    await waitFor(() =>
      expect(screen.getByLabelText("Test design")).toHaveValue("bundled-on-dark"),
    );
  });

  it("reports a new selection by id", async () => {
    const { onChange } = renderPicker();
    const select = await screen.findByLabelText("Test design");
    fireEvent.change(select, { target: { value: "bundled-on-light" } });
    expect(onChange).toHaveBeenCalledWith("bundled-on-light");
  });

  it("separates uploads from the bundled targets", async () => {
    renderPicker([...BUNDLED, { id: "my-art", label: "my-art", source: "upload" }]);
    await screen.findByLabelText("Test design");
    const groups = [...document.querySelectorAll("optgroup")].map((g) => g.label);
    expect(groups).toEqual(["Bundled", "My uploads"]);
  });

  it("uploads a PNG, adds it to the library and selects it", async () => {
    vi.spyOn(calibrator, "listDesigns").mockResolvedValue(BUNDLED);
    const uploadSpy = vi.spyOn(calibrator, "uploadDesign").mockResolvedValue({
      id: "my-art",
      label: "my-art",
      source: "upload",
    });
    const onChange = vi.fn();
    render(<TestDesignPicker value="bundled-grid" onChange={onChange} />);
    await screen.findByLabelText("Test design");

    const file = new File(["x"], "my-art.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText(/Upload a PNG/), { target: { files: [file] } });

    await waitFor(() => expect(uploadSpy).toHaveBeenCalledWith(file));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith("my-art"));
    // ...and it is selectable straight away, without a reload
    await waitFor(() =>
      expect(screen.getByLabelText("Test design").querySelector("option[value='my-art']")).not.toBe(
        null,
      ),
    );
  });

  it("says so when the upload is rejected, rather than failing silently", async () => {
    vi.spyOn(calibrator, "listDesigns").mockResolvedValue(BUNDLED);
    vi.spyOn(calibrator, "uploadDesign").mockRejectedValue(new Error("not an image"));
    render(<TestDesignPicker value="bundled-grid" onChange={vi.fn()} />);
    await screen.findByLabelText("Test design");

    fireEvent.change(screen.getByLabelText(/Upload a PNG/), {
      target: { files: [new File(["x"], "notes.txt")] },
    });
    await screen.findByText("upload failed");
  });

  it("survives the library failing to load", async () => {
    vi.spyOn(calibrator, "listDesigns").mockRejectedValue(new Error("network"));
    render(<TestDesignPicker value="bundled-grid" onChange={vi.fn()} />);
    await screen.findByText("could not load test designs");
  });
});
