import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BatchCandidateControl } from "./BatchCandidateControl";

describe("BatchCandidateControl", () => {
  it("reveals candidate names when the control is hovered", () => {
    render(
      <BatchCandidateControl
        names={{ add: ["new-shirt"], edit: [], remove: [] }}
        onDeploy={vi.fn()}
      />,
    );

    const button = screen.getByRole("button", { name: /deploy changes/i });
    fireEvent.mouseEnter(button);

    expect(screen.getByRole("tooltip")).toHaveTextContent("new-shirt");
  });

  it("reveals candidate counts and names on keyboard focus", () => {
    render(
      <BatchCandidateControl
        names={{
          add: ["new-shirt", "second-shirt"],
          edit: ["updated-shirt"],
          remove: ["retired-shirt"],
        }}
        onDeploy={vi.fn()}
      />,
    );

    const button = screen.getByRole("button", { name: /deploy changes/i });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    fireEvent.focus(button);

    expect(screen.getByRole("tooltip")).toHaveTextContent("Add");
    expect(screen.getByRole("tooltip")).toHaveTextContent("new-shirt");
    expect(screen.getByRole("tooltip")).toHaveTextContent("1 to remove");
    expect(button).toHaveAccessibleName("Deploy changes: 2 to add, 1 to remove, 1 to edit");
  });

  it("activates the deploy callback from the native button", () => {
    const onDeploy = vi.fn();
    render(<BatchCandidateControl names={{ add: [], edit: [], remove: [] }} onDeploy={onDeploy} />);

    fireEvent.click(screen.getByRole("button", { name: "Deploy changes" }));

    expect(onDeploy).toHaveBeenCalledOnce();
  });
});
