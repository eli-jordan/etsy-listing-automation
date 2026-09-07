import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ViewTabs } from "./ViewTabs";

describe("ViewTabs", () => {
  it("marks the current view and reports a switch", () => {
    const onChange = vi.fn();
    render(<ViewTabs value="calibrate" onChange={onChange} />);

    expect(screen.getByRole("tab", { name: "Calibrate" })).toHaveAttribute("aria-selected", "true");
    // No count in the label: one preview or twelve, it is the same view.
    fireEvent.click(screen.getByRole("tab", { name: "Preview" }));
    expect(onChange).toHaveBeenCalledWith("preview");
  });
});
