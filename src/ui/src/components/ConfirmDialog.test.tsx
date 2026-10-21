import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog } from "./ConfirmDialog";

describe("ConfirmDialog", () => {
  it("asks its question and confirms", () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        title="Retract it?"
        confirmLabel="Retract"
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByRole("dialog", { name: "Retract it?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retract" }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("renders a body between the question and the actions", () => {
    render(
      <ConfirmDialog title="Pick one" confirmLabel="Use it" onConfirm={vi.fn()} onCancel={vi.fn()}>
        <p>Pick the one to keep.</p>
      </ConfirmDialog>,
    );
    expect(screen.getByText("Pick the one to keep.")).toBeInTheDocument();
  });

  it("holds the confirm back while the body has no answer", () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        title="Pick one"
        confirmLabel="Use it"
        confirmDisabled
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );
    const confirm = screen.getByRole("button", { name: "Use it" });
    expect(confirm).toBeDisabled();
    fireEvent.click(confirm);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("cancels on Cancel, on Escape and on the backdrop", () => {
    const onCancel = vi.fn();
    const { container } = render(
      <ConfirmDialog
        title="Retract it?"
        confirmLabel="Retract"
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.click(container.querySelector(".modal-backdrop") as Element);
    expect(onCancel).toHaveBeenCalledTimes(3);
  });
});
