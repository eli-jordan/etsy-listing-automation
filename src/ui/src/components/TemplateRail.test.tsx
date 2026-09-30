import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { TemplateSummary } from "../types";
import { TemplateRail } from "./TemplateRail";

/** Wireframe 2a replaces the template dropdown with a rail that leads with
 * what still needs work -- so most of what is worth testing here is the
 * ordering, grouping and filtering, not the markup. */

function summary(over: Partial<TemplateSummary> & { name: string }): TemplateSummary {
  return {
    kind: "colour-matrix",
    colours: [],
    photos: [],
    has_config: true,
    status: "calibrated",
    status_reason: null,
    ...over,
  };
}

const NEEDS_KIND = summary({
  name: "boxy-tee",
  kind: null,
  has_config: false,
  status: "needs-calibration",
  status_reason: "no kind set",
});
const NEEDS_BOXES = summary({
  name: "tote",
  kind: "multiple",
  status: "needs-calibration",
  status_reason: "no boxes",
});
const DONE_MATRIX = summary({
  name: "heather-tee",
  colours: ["sand", "black", "navy"],
});
const DONE_CHART = summary({ name: "rack-shot", kind: "multiple", colours: ["sand", "black"] });

const ALL = [DONE_MATRIX, NEEDS_KIND, DONE_CHART, NEEDS_BOXES];

function renderRail(over: Partial<Parameters<typeof TemplateRail>[0]> = {}) {
  const onSelect = vi.fn();
  render(<TemplateRail templates={ALL} selected={null} onSelect={onSelect} {...over} />);
  return { onSelect };
}

function rowNames(): string[] {
  return screen
    .getAllByRole("button")
    .map((b) => b.getAttribute("data-template"))
    .filter((n): n is string => n !== null);
}

describe("TemplateRail", () => {
  it("sorts templates that need calibration above the finished ones", () => {
    renderRail();
    expect(rowNames()).toEqual(["boxy-tee", "tote", "heather-tee", "rack-shot"]);
  });

  it("groups each half under a heading carrying its count", () => {
    renderRail();
    expect(screen.getByText("Needs calibration · 2")).toBeInTheDocument();
    expect(screen.getByText("Calibrated · 2")).toBeInTheDocument();
  });

  it("explains why each unfinished template is unfinished", () => {
    renderRail();
    expect(screen.getByText(/no kind set/)).toBeInTheDocument();
    expect(screen.getByText(/no boxes/)).toBeInTheDocument();
  });

  it("describes a finished template by kind and colour count", () => {
    renderRail();
    expect(screen.getByText("Colour Matrix · 3 colours")).toBeInTheDocument();
  });

  it("uses the singular for a one-colour template", () => {
    renderRail({ templates: [summary({ name: "solo", colours: ["sand"] })] });
    expect(screen.getByText("Colour Matrix · 1 colour")).toBeInTheDocument();
  });

  it("banners the outstanding count and jumps to the first one", () => {
    const { onSelect } = renderRail();
    expect(screen.getByText("2 templates need calibration")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Calibrate next/ }));
    expect(onSelect).toHaveBeenCalledWith("boxy-tee");
  });

  it("uses the singular in the banner for one outstanding template", () => {
    renderRail({ templates: [NEEDS_KIND, DONE_MATRIX] });
    expect(screen.getByText("1 template needs calibration")).toBeInTheDocument();
  });

  it("hides the banner once everything is calibrated", () => {
    renderRail({ templates: [DONE_MATRIX, DONE_CHART] });
    expect(screen.queryByText(/need.? calibration$/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Calibrate next/ })).not.toBeInTheDocument();
  });

  it("filters by name as you search", () => {
    renderRail();
    fireEvent.change(screen.getByLabelText("Search templates"), {
      target: { value: "tee" },
    });
    expect(rowNames()).toEqual(["boxy-tee", "heather-tee"]);
  });

  it("narrows to just the unfinished ones", () => {
    renderRail();
    fireEvent.click(screen.getByRole("button", { name: /Needs calibration 2/ }));
    expect(rowNames()).toEqual(["boxy-tee", "tote"]);
  });

  it("narrows to just the finished ones", () => {
    renderRail();
    fireEvent.click(screen.getByRole("button", { name: /Done 2/ }));
    expect(rowNames()).toEqual(["heather-tee", "rack-shot"]);
  });

  it("narrows by kind, and clears the filter when the pill is pressed again", () => {
    renderRail();
    const pill = screen.getByRole("button", { name: "Multiple" });
    fireEvent.click(pill);
    expect(rowNames()).toEqual(["tote", "rack-shot"]);
    fireEvent.click(pill);
    expect(rowNames()).toEqual(["boxy-tee", "tote", "heather-tee", "rack-shot"]);
  });

  it("selects a template when its row is clicked", () => {
    const { onSelect } = renderRail();
    fireEvent.click(screen.getByRole("button", { name: /heather-tee/ }));
    expect(onSelect).toHaveBeenCalledWith("heather-tee");
  });

  it("marks the selected row for the styling layer", () => {
    renderRail({ selected: "tote" });
    const row = screen.getByRole("button", { name: /tote/ });
    expect(row.className).toContain("template-rail__item--active");
  });

  it("truncates a long group and reveals the rest on demand", () => {
    const many = Array.from({ length: 9 }, (_, i) => summary({ name: `t-${i}` }));
    renderRail({ templates: many });
    expect(rowNames()).toHaveLength(5);
    fireEvent.click(screen.getByRole("button", { name: "+ 4 more" }));
    expect(rowNames()).toHaveLength(9);
  });

  it("falls back to a blank tile when a template has no photo to thumbnail", () => {
    // A directory can exist before any photo is in it -- an interrupted
    // upload, or a folder made by hand -- and /thumbnail 404s for those. Left
    // alone the browser draws its broken-image icon, which reads as a bug in
    // the rail rather than as "this template has nothing in it yet".
    renderRail({ templates: [NEEDS_KIND] });
    const img = screen.getByRole("presentation", { hidden: true });
    fireEvent.error(img);
    expect(screen.queryByRole("presentation", { hidden: true })).not.toBeInTheDocument();
    expect(document.querySelector(".template-rail__thumb--empty")).toBeInTheDocument();
  });

  it("says so when a search matches nothing, rather than showing an empty rail", () => {
    renderRail();
    fireEvent.change(screen.getByLabelText("Search templates"), {
      target: { value: "zzz" },
    });
    expect(screen.getByText("No templates match.")).toBeInTheDocument();
    expect(rowNames()).toEqual([]);
  });
});
