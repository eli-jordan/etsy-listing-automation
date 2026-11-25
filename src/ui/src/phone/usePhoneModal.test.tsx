import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { onPhone } from "../test/touch";
import { usePhoneModal } from "./usePhoneModal";

function Sheet({ onClose }: { onClose: (() => void) | null }) {
  const box = useRef<HTMLDivElement>(null);
  usePhoneModal(box, { onClose });
  return (
    <div ref={box} data-testid="sheet">
      <button type="button">First</button>
      <button type="button">Last</button>
    </div>
  );
}

function Page({ dismissible = true }: { dismissible?: boolean }) {
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open
      </button>
      <button type="button">Behind</button>
      {open && <Sheet onClose={dismissible ? close : null} />}
      {open && (
        <button type="button" onClick={close}>
          Done
        </button>
      )}
    </>
  );
}

/** A closed sheet drops its history entry a tick later, and jsdom pops it
 * a tick after that. */
const entryDropped = () => waitFor(() => expect(window.history.state?.phoneSheet).toBeUndefined());

function openSheet() {
  const opener = screen.getByRole("button", { name: "Open" });
  opener.focus();
  fireEvent.click(opener);
  return opener;
}

afterEach(async () => {
  cleanup();
  await entryDropped();
  vi.unstubAllGlobals();
  document.body.style.overflow = "";
});

describe("usePhoneModal on a phone", () => {
  beforeEach(() => onPhone());

  it("locks the page's scroll while open, and puts it back after", () => {
    render(<Page />);
    openSheet();
    expect(document.body.style.overflow).toBe("hidden");
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(document.body.style.overflow).toBe("");
  });

  it("takes focus, keeps Tab inside, and hands focus back to the opener", () => {
    render(<Page />);
    const opener = openSheet();
    expect(document.activeElement).toBe(screen.getByTestId("sheet"));

    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "First" }));
    screen.getByRole("button", { name: "Last" }).focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "First" }));
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Last" }));

    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(document.activeElement).toBe(opener);
  });

  it("closes on Back without leaving the page, and drops its entry when closed otherwise", async () => {
    render(<Page />);
    openSheet();
    expect(window.history.state?.phoneSheet).toBeDefined();
    act(() => window.history.back());
    await waitFor(() => expect(screen.queryByTestId("sheet")).toBeNull());

    openSheet();
    expect(window.history.state?.phoneSheet).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(window.history.state?.phoneSheet).toBeDefined();
    await entryDropped();
  });

  it("leaves history alone for a sheet that cannot be dismissed", () => {
    render(<Page dismissible={false} />);
    openSheet();
    expect(window.history.state?.phoneSheet).toBeUndefined();
    expect(document.body.style.overflow).toBe("hidden");
  });
});

describe("usePhoneModal off the phone", () => {
  beforeEach(() => onPhone({ phone: false }));

  it("does nothing", () => {
    render(<Page />);
    const opener = openSheet();
    expect(document.body.style.overflow).toBe("");
    expect(document.activeElement).toBe(opener);
    expect(window.history.state?.phoneSheet).toBeUndefined();
    expect(screen.getByTestId("sheet").hasAttribute("tabindex")).toBe(false);
  });
});
