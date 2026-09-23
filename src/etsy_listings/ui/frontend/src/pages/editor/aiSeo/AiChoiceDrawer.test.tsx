import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { SeoRationaleEntry, SeoWarningEntry } from "../../../types";
import { AiChoiceDrawer } from "./AiChoiceDrawer";

const rationale: SeoRationaleEntry[] = [
  {
    phrase: "hiking tee",
    intent: "core_product",
    reason: "matches search intent",
    used_in: ["title"],
  },
  {
    phrase: "gift for hikers",
    intent: "bottom_of_funnel",
    reason: "gift intent",
    used_in: ["tags"],
  },
];

const warnings: SeoWarningEntry[] = [{ kind: "trademark", message: "avoid brand name X" }];

describe("AiChoiceDrawer", () => {
  it("labels the drawer with the field it affects", () => {
    render(
      <AiChoiceDrawer
        field="title"
        options={["Title A", "Title B", "Title C"]}
        stale={false}
        rationale={[]}
        warnings={[]}
        observedText=""
        onChoose={vi.fn()}
        onReject={vi.fn()}
      />,
    );
    expect(screen.getByRole("region", { name: "title AI suggestions" })).toBeInTheDocument();
  });

  it("calls onChoose with the activated option", async () => {
    const onChoose = vi.fn();
    render(
      <AiChoiceDrawer
        field="description lead"
        options={["Lead A", "Lead B"]}
        stale={false}
        rationale={[]}
        warnings={[]}
        observedText=""
        onChoose={onChoose}
        onReject={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Lead B/ }));
    expect(onChoose).toHaveBeenCalledWith("Lead B");
  });

  it("calls onReject when Reject all is activated", async () => {
    const onReject = vi.fn();
    render(
      <AiChoiceDrawer
        field="title"
        options={["Title A"]}
        stale={false}
        rationale={[]}
        warnings={[]}
        observedText=""
        onChoose={vi.fn()}
        onReject={onReject}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /reject all/i }));
    expect(onReject).toHaveBeenCalled();
  });

  it("disables every option and marks the drawer stale when stale", () => {
    render(
      <AiChoiceDrawer
        field="title"
        options={["Title A", "Title B"]}
        stale={true}
        rationale={[]}
        warnings={[]}
        observedText=""
        onChoose={vi.fn()}
        onReject={vi.fn()}
      />,
    );
    expect(screen.getByText(/out of date/i)).toBeInTheDocument();
    for (const button of screen.getAllByRole("button", { name: /Title/ })) {
      expect(button).toBeDisabled();
    }
  });

  it("exposes rationale filtered to this field, warnings, and observed OCR text as a disclosure", () => {
    render(
      <AiChoiceDrawer
        field="title"
        options={["Title A"]}
        stale={false}
        rationale={rationale}
        warnings={warnings}
        observedText="TAKE A HIKE"
        onChoose={vi.fn()}
        onReject={vi.fn()}
      />,
    );
    // Only the title-relevant rationale entry appears, not the tags one.
    expect(screen.getByText(/matches search intent/)).toBeInTheDocument();
    expect(screen.queryByText(/gift intent/)).not.toBeInTheDocument();
    expect(screen.getByText(/avoid brand name X/)).toBeInTheDocument();
    expect(screen.getByText("TAKE A HIKE")).toBeInTheDocument();
  });

  it("omits the disclosure entirely when there is nothing to disclose", () => {
    render(
      <AiChoiceDrawer
        field="title"
        options={["Title A"]}
        stale={false}
        rationale={[]}
        warnings={[]}
        observedText=""
        onChoose={vi.fn()}
        onReject={vi.fn()}
      />,
    );
    expect(screen.queryByText(/why these suggestions/i)).not.toBeInTheDocument();
  });

  it("has a ref-able first option for focus management", () => {
    render(
      <AiChoiceDrawer
        field="title"
        options={["Title A", "Title B"]}
        stale={false}
        rationale={[]}
        warnings={[]}
        observedText=""
        onChoose={vi.fn()}
        onReject={vi.fn()}
      />,
    );
    const region = screen.getByRole("region", { name: "title AI suggestions" });
    const firstButton = screen.getByRole("button", { name: /Title A/ });
    expect(region.querySelector(".seo-choice-list button")).toBe(firstButton);
  });
});
