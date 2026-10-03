import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EditableName } from "./EditableName";

describe("EditableName", () => {
  it("opens in edit mode when there is no name yet", () => {
    render(<EditableName value="" onCommit={vi.fn()} />);
    expect(screen.getByLabelText("Listing name")).toBeTruthy();
  });

  it("shows a name it has as a heading until it is double-clicked", () => {
    render(<EditableName value="take-a-hike" onCommit={vi.fn()} />);
    expect(screen.queryByLabelText("Listing name")).toBeNull();

    fireEvent.doubleClick(screen.getByRole("heading"));
    expect(screen.getByLabelText("Listing name")).toBeTruthy();
  });

  it("opens on Enter too, so renaming is not mouse-only", () => {
    render(<EditableName value="take-a-hike" onCommit={vi.fn()} />);
    fireEvent.keyDown(screen.getByRole("heading"), { key: "Enter" });
    expect(screen.getByLabelText("Listing name")).toBeTruthy();
  });

  it("commits the trimmed text on Enter", () => {
    const onCommit = vi.fn();
    render(<EditableName value="" onCommit={onCommit} />);

    const input = screen.getByLabelText("Listing name");
    fireEvent.change(input, { target: { value: "  my-shirt  " } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onCommit).toHaveBeenCalledWith("my-shirt");
  });

  it("commits on blur", () => {
    const onCommit = vi.fn();
    render(<EditableName value="" onCommit={onCommit} />);

    const input = screen.getByLabelText("Listing name");
    fireEvent.change(input, { target: { value: "my-shirt" } });
    fireEvent.blur(input);

    expect(onCommit).toHaveBeenCalledWith("my-shirt");
  });

  it("does not commit an empty name", () => {
    const onCommit = vi.fn();
    render(<EditableName value="" onCommit={onCommit} />);

    fireEvent.keyDown(screen.getByLabelText("Listing name"), { key: "Enter" });
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("does not commit a name that has not changed", () => {
    const onCommit = vi.fn();
    render(<EditableName value="take-a-hike" onCommit={onCommit} />);

    fireEvent.doubleClick(screen.getByRole("heading"));
    fireEvent.blur(screen.getByLabelText("Listing name"));

    expect(onCommit).not.toHaveBeenCalled();
  });

  it("reverts on Escape without committing, so a stray double-click costs nothing", () => {
    const onCommit = vi.fn();
    render(<EditableName value="take-a-hike" onCommit={onCommit} />);

    fireEvent.doubleClick(screen.getByRole("heading"));
    const input = screen.getByLabelText("Listing name");
    fireEvent.change(input, { target: { value: "something-else" } });
    fireEvent.keyDown(input, { key: "Escape" });
    fireEvent.blur(input);

    expect(onCommit).not.toHaveBeenCalled();
    expect(screen.getByRole("heading").textContent).toBe("take-a-hike");
  });

  it("shows a refusal from the server and re-opens the field", () => {
    render(
      <EditableName
        value="take-a-hike"
        onCommit={vi.fn()}
        error={{ name: "take-a-hike", message: "that name is taken" }}
      />,
    );
    expect(screen.getByRole("alert").textContent).toBe("that name is taken");
    expect(screen.getByLabelText("Listing name")).toBeTruthy();
  });

  it("clears the refusal once the name is being typed over", () => {
    render(
      <EditableName
        value=""
        onCommit={vi.fn()}
        error={{ name: "", message: "that name is taken" }}
      />,
    );
    fireEvent.change(screen.getByLabelText("Listing name"), { target: { value: "other" } });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("is read-only while a commit is in flight", () => {
    render(<EditableName value="" onCommit={vi.fn()} busy />);
    expect(screen.getByLabelText("Listing name").hasAttribute("readonly")).toBe(true);
  });
});
