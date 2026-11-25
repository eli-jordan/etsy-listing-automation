import { type ReactNode, useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { SheetGrabber } from "../../phone/SheetGrabber";

/**
 * A bottom sheet the phone layout opens in place of a desktop popover or
 * side panel: the editor's overflow actions, Add media, the save card.
 *
 * On `document.body`, never inside the tab content: the tab content swipes
 * sideways between tabs, and a sheet's own grab bar must not be read as a
 * swipe of the tab under it.
 *
 * `open` hides it rather than unmounting it, so what is inside keeps its
 * state while it is closed -- a delete confirmation started from the
 * overflow sheet outlives the sheet closing under it.
 */
export function PhoneSheet({
  open,
  title,
  onClose,
  className,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  className?: string;
  children: ReactNode;
}) {
  const sheet = useRef<HTMLDivElement>(null);
  const titleId = useId();

  useEffect(() => {
    if (!open) return;
    // A previous swipe-to-dismiss left the sheet translated off screen.
    const box = sheet.current;
    if (box) {
      box.style.transition = "";
      box.style.transform = "";
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Closed, it keeps the same element tree, so nothing inside remounts, but
  // without the dialog's role and classes: a hidden sheet is not a dialog.
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
        {open && <SheetGrabber sheetRef={sheet} onDismiss={onClose} />}
        <div className="phone-sheet__head">
          <h2 id={titleId} className="phone-sheet__title">
            {title}
          </h2>
          <button type="button" className="phone-sheet__done" onClick={onClose}>
            Done
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
