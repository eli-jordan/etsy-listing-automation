import { fireEvent, renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useMenuDismiss } from "./useMenuDismiss";

it("dismisses on an outside click or Escape and removes listeners on unmount", () => {
  const inside = document.createElement("div");
  document.body.append(inside);
  const ref = { current: inside };
  const setOpen = vi.fn();
  const { unmount } = renderHook(() => useMenuDismiss(true, ref, setOpen));
  fireEvent.mouseDown(inside);
  expect(setOpen).not.toHaveBeenCalled();
  fireEvent.mouseDown(document.body);
  expect(setOpen).toHaveBeenCalledWith(false);
  setOpen.mockClear();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(setOpen).toHaveBeenCalledWith(false);
  unmount();
  setOpen.mockClear();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(setOpen).not.toHaveBeenCalled();
  inside.remove();
});
