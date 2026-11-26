import { fireEvent, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { expect, it, vi } from "vitest";
import { useModalKeys } from "./useModalKeys";

function Dialog({ onCancel }: { onCancel: () => void }) {
  const dialog = useRef<HTMLDivElement>(null);
  useModalKeys(dialog, onCancel);
  return (
    <div ref={dialog} role="dialog">
      <p>Some text that cannot take focus.</p>
      <button type="button">First</button>
      <button type="button">Last</button>
    </div>
  );
}

it("keeps Tab inside the dialog after a click on its text has left focus on the body", () => {
  render(<Dialog onCancel={() => {}} />);
  fireEvent.click(screen.getByText("Some text that cannot take focus."));
  expect(document.activeElement).toBe(document.body);

  fireEvent.keyDown(document.body, { key: "Tab" });

  expect(screen.getByRole("button", { name: "First" })).toHaveFocus();
});

it("wraps Tab and Shift+Tab around the dialog's controls", () => {
  render(<Dialog onCancel={() => {}} />);
  screen.getByRole("button", { name: "Last" }).focus();

  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Tab" });
  expect(screen.getByRole("button", { name: "First" })).toHaveFocus();

  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Tab", shiftKey: true });
  expect(screen.getByRole("button", { name: "Last" })).toHaveFocus();
});

it("cancels on Escape", () => {
  const onCancel = vi.fn();
  render(<Dialog onCancel={onCancel} />);

  fireEvent.keyDown(document.body, { key: "Escape" });

  expect(onCancel).toHaveBeenCalledOnce();
});
