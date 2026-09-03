import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../api/calibrator";
import type { SingleTemplate } from "../types";
import { SingleEditor } from "./SingleEditor";

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

describe("SingleEditor", () => {
  it("fetches a preview with no colour selector and renders the box editor", async () => {
    const spy = vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    render(<SingleEditor templateName="lifestyle-01" config={CONFIG} onChange={vi.fn()} />);

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith("lifestyle-01", {
        bounding_box: CONFIG.bounding_box,
        displace: CONFIG.displace,
        shade: CONFIG.shade,
      }),
    );
    await screen.findByAltText("Rendered preview");
  });

  it("editing the colour field updates the config", async () => {
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    const onChange = vi.fn();
    render(<SingleEditor templateName="lifestyle-01" config={CONFIG} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText("Garment colour (optional)"), {
      target: { value: "black" },
    });
    expect(onChange).toHaveBeenCalledWith({ ...CONFIG, colour: "black" });
  });
});
