import { type ReactNode, useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { SheetGrabber } from "./SheetGrabber";

/**
 * The phone layout's bottom sheet, for what a desktop shows as a popover, a
 * side panel or an inline row of actions: `ConfirmDialog`'s sheet, with a grab
 * bar and title row that drag it away, and Done unless `done` is false.
 *
 * On `document.body`: the editor's tab content swipes sideways, and a sheet's
 * drag must not read as a swipe of the tab under it. `open` hides it rather
 * than unmounting it, so what is inside keeps its state while it is closed.
 */
export function PhoneSheet({
  open = true,
  title,
  onClose,
  done = true,
  className,
  children,
}: {
  open?: boolean;
  title: string;
  onClose: () => void;
  done?: boolean;
  className?: string;
  children: ReactNode;
}) {
  const sheet = useRef<HTMLDivElement>(null);
  const head = useRef<HTMLDivElement>(null);
  const titleId = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return createPortal(
    <div
      className={open ? "modal-root phone-sheet" : "phone-sheet"}
      role={open ? "dialog" : undefined}
      aria-modal={open ? true : undefined}
      aria-labelledby={open ? titleId : undefined}
      hidden={!open}
    >
      {open && <div className="modal-backdrop" onClick={onClose} aria-hidden="true" />}
      <div
        ref={sheet}
        className={[open ? "modal-dialog phone-sheet__box" : "phone-sheet__box", className]
          .filter(Boolean)
          .join(" ")}
      >
        {open && <SheetGrabber sheetRef={sheet} onDismiss={onClose} head={head} />}
        <div ref={head} className="phone-sheet__head">
          <h2 id={titleId} className="phone-sheet__title">
            {title}
          </h2>
          {done && (
            <button type="button" className="phone-sheet__done" onClick={onClose}>
              Done
            </button>
          )}
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
