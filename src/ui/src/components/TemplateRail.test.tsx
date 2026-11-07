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
    labels: [],
    status: "calibrated",
    status_reason: null,
    ...over,
  };
}

const NEEDS_KIND = summary({
  name: "boxy-tee",
  kind: null,
  has_config: false,
  labels: [],
  status: "needs-calibration",
  status_reason: "no kind set",
});
const NEEDS_BOXES = summary({
  name: "tote",
  kind: "multiple",
  labels: [],
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

  it("lists a template's labels on its row", () => {
    renderRail({ templates: [summary({ name: "tee", labels: ["theme:christmas", "cosy"] })] });

    expect(screen.getByText("theme:christmas · cosy")).toBeInTheDocument();
    expect(screen.queryByText("No labels")).not.toBeInTheDocument();
  });

  it("says when a template has no labels", () => {
    renderRail({ templates: [summary({ name: "tee" })] });

    expect(screen.getByText("No labels")).toBeInTheDocument();
  });

  it("filters by name as you search", () => {
    renderRail();
    fireEvent.change(screen.getByRole("combobox", { name: /Search templates/ }), {
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
    fireEvent.change(screen.getByRole("combobox", { name: /Search templates/ }), {
      target: { value: "zzz" },
    });
    expect(screen.getByText("No templates match.")).toBeInTheDocument();
    expect(rowNames()).toEqual([]);
  });
});

it("keeps unknown Marigold readiness out of ready and needs-map filters", () => {
  renderRail({ templates: [summary({ name: "pending", renderer: "marigold", maps: null })] });
  expect(screen.getByText("Checking maps")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Ready 0" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Needs maps 0" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Ready 0" }));
  expect(rowNames()).toEqual([]);
});

describe("the rail's label search", () => {
  const SNOW = summary({ name: "snow-tee", labels: ["theme:christmas", "model:female"] });
  const TREE = summary({ name: "tree-tee", labels: ["theme:christmas"] });
  const BEACH = summary({ name: "beach-tote", kind: "multiple", labels: ["theme:summer"] });
  const WAITING = summary({
    name: "elf-tee",
    labels: ["theme:elves"],
    status: "needs-calibration",
    status_reason: "no boxes",
  });
  const LABELLED = [SNOW, TREE, BEACH, WAITING];

  const box = () => screen.getByRole("combobox", { name: /Search templates/ });
  const options = () => screen.queryAllByRole("option").map((o) => o.textContent);

  function pick(label: string) {
    fireEvent.click(box());
    fireEvent.click(screen.getByRole("option", { name: new RegExp(label) }));
  }

  it("lists only the templates holding every pill", () => {
    renderRail({ templates: LABELLED });
    pick("theme:christmas");
    expect(rowNames()).toEqual(["snow-tee", "tree-tee"]);
    pick("model:female");
    expect(rowNames()).toEqual(["snow-tee"]);
  });

  it("finds a hand-edited label whatever its case", () => {
    const edited = summary({ name: "edited-tee", labels: ["Theme:Christmas"] });
    renderRail({ templates: [...LABELLED, edited] });
    pick("theme:christmas");
    expect(rowNames()).toEqual(["snow-tee", "tree-tee", "edited-tee"]);
  });

  it("searches titles on top of the pills", () => {
    renderRail({ templates: LABELLED });
    pick("theme:christmas");
    fireEvent.change(box(), { target: { value: "TREE" } });
    expect(rowNames()).toEqual(["tree-tee"]);
  });

  it("searches names only: text in a label lists nothing by itself", () => {
    renderRail({ templates: LABELLED });
    fireEvent.change(box(), { target: { value: "christmas" } });
    expect(rowNames()).toEqual([]);
    expect(options()).toEqual(["theme:christmas2"]);
  });

  it("counts only what the status pill leaves", () => {
    renderRail({ templates: LABELLED });
    fireEvent.click(screen.getByRole("button", { name: "Needs calibration 1" }));
    fireEvent.click(box());
    expect(options()).toEqual(["theme:elves1"]);
  });

  it("counts only what the kind pill leaves", () => {
    renderRail({ templates: LABELLED });
    fireEvent.click(screen.getByRole("button", { name: "Colour Matrix" }));
    fireEvent.click(box());
    expect(options()).toEqual(["model:female1", "theme:christmas2", "theme:elves1"]);
  });

  it("keeps the pills and text through switching template and a catalog refresh", () => {
    const onSelect = vi.fn();
    const rail = (templates: TemplateSummary[], selected: string | null) => (
      <TemplateRail templates={templates} selected={selected} onSelect={onSelect} />
    );
    const { rerender } = render(rail(LABELLED, null));
    pick("theme:christmas");
    fireEvent.change(box(), { target: { value: "snow" } });

    rerender(rail(LABELLED, "snow-tee"));
    rerender(rail([...LABELLED], "snow-tee"));

    expect(screen.getByRole("button", { name: "Remove theme:christmas" })).toBeInTheDocument();
    expect(box()).toHaveValue("snow");
    expect(rowNames()).toEqual(["snow-tee"]);
  });

  it("starts empty again after leaving the page", () => {
    const { unmount } = render(
      <TemplateRail templates={LABELLED} selected={null} onSelect={vi.fn()} />,
    );
    pick("theme:christmas");
    fireEvent.change(box(), { target: { value: "snow" } });
    unmount();

    renderRail({ templates: LABELLED });
    expect(screen.queryByRole("button", { name: /^Remove / })).not.toBeInTheDocument();
    expect(box()).toHaveValue("");
    expect(rowNames()).toHaveLength(4);
  });
});
