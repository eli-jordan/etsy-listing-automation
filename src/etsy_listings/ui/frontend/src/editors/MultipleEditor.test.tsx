import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../api/calibrator";
import { must } from "../test/helpers";
import type { MultipleTemplate } from "../types";
import { MultipleEditor } from "./MultipleEditor";

const CONFIG: MultipleTemplate = {
  kind: "multiple",
  colour_coverage: "exact",
  placements: [
    {
      colour: "black",
      bounding_box: [
        { x: 0, y: 0 },
        { x: 100, y: 0 },
        { x: 100, y: 100 },
        { x: 0, y: 100 },
      ],
    },
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

describe("MultipleEditor", () => {
  it("fetches a preview of the whole scene (all placements, no colour selector)", async () => {
    const spy = vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    render(<MultipleEditor templateName="colour-chart-01" config={CONFIG} onChange={vi.fn()} design="bundled-grid" onDesignChange={vi.fn()} knownColours={[]} />);

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        "colour-chart-01",
        {
          placements: CONFIG.placements,
          displace: CONFIG.displace,
          shade: CONFIG.shade,
        },
        "bundled-grid",
      ),
    );
  });

  it("adding a placement via the panel updates the config", async () => {
    vi.spyOn(calibrator, "renderPreview").mockResolvedValue("blob:preview");
    const onChange = vi.fn();
    render(<MultipleEditor templateName="colour-chart-01" config={CONFIG} onChange={onChange} design="bundled-grid" onDesignChange={vi.fn()} knownColours={[]} />);

    fireEvent.click(screen.getByRole("button", { name: "+ Add" }));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ placements: expect.arrayContaining([expect.any(Object)]) }),
    );
    expect(must(onChange.mock.calls[0])[0].placements).toHaveLength(2);
  });
});
