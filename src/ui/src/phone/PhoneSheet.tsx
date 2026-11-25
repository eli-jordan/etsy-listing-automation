import { type ReactNode, useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { SheetGrabber } from "./SheetGrabber";

/**
 * The phone layout's bottom sheet, for what a desktop shows as a popover, a
 * side panel or an inline row of actions: the editor's overflow actions and
 * Add media, a listing row's actions, the template switcher.
 *
 * It is the same sheet as `ConfirmDialog` (`.modal-root` / `.modal-dialog`,
 * drawn as a sheet by `phone/base.css`) with a grab bar that swipes it away,
 * a title, and Done unless `done` is false (an action sheet ends in its own
 * Cancel instead).
 *
 * On `document.body`, never inside the page: the editor's tab content swipes
 * sideways between tabs, and a sheet's own grab bar must not be read as a
 * swipe of the tab under it; the calibrator's narrow-width rules must not
 * reach a copy of the rail inside one.
 *
 * `open` hides it rather than unmounting it, so what is inside keeps its
 * state while it is closed -- a delete confirmation started from the
 * overflow sheet outlives the sheet closing under it. A caller that mounts
 * it only while open leaves `open` at its default.
 *
 * Only the phone layout opens one, so its markup has no desktop styles.
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
  /** Extra class on the sheet box, for an area's own look. */
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
