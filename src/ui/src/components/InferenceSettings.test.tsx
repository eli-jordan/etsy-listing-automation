import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InferenceSettings } from "./InferenceSettings";

describe("Advanced Marigold Settings", () => {
  it("keeps reset and edits in a draft until Save settings", () => {
    const save = vi.fn();
    render(
      <InferenceSettings
        templateName="tee"
        value={{ num_inference_steps: 20, ensemble_size: 5 }}
        onSave={save}
      />,
    );
    fireEvent.click(screen.getByText(/Advanced settings/));
    expect(screen.getByLabelText("Inference steps")).toHaveFocus();
    fireEvent.click(screen.getByText("Reset to defaults"));
    expect(save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Save settings"));
    expect(save).toHaveBeenCalledWith({ num_inference_steps: 10, ensemble_size: 3 });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText(/Advanced settings/)).toHaveFocus();
  });
  it("discards changes on Escape and rejects fractional values", () => {
    const save = vi.fn();
    render(
      <InferenceSettings
        templateName="tee"
        value={{ num_inference_steps: 10, ensemble_size: 3 }}
        onSave={save}
      />,
    );
    fireEvent.click(screen.getByText(/Advanced settings/));
    fireEvent.change(screen.getByLabelText("Inference steps"), { target: { value: "1.5" } });
    expect(screen.getByText("Save settings")).toBeDisabled();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText(/Advanced settings/));
    expect(screen.getByLabelText("Inference steps")).toHaveValue(10);
  });
});

it("uses conservative supported limits while runtime capability is pending", () => {
  render(
    <InferenceSettings
      templateName="tee"
      value={{ num_inference_steps: 10, ensemble_size: 3 }}
      onSave={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByText(/Advanced settings/));
  expect(screen.getByLabelText("Inference steps")).toHaveAttribute("max", "10");
  expect(screen.getByLabelText("Ensemble size")).toHaveAttribute("max", "3");
  expect(screen.getByText(/Checking runtime capability/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Inference steps"), { target: { value: "11" } });
  expect(screen.getByText("Save settings")).toBeDisabled();
});
