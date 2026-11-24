import { useEffect, useId, useRef } from "react";
import { SheetGrabber } from "../../phone/SheetGrabber";

/**
 * A phone action sheet: a row's secondary actions, which a table row shows
 * inline and a phone row has no room for. It is the same bottom sheet as
 * `ConfirmDialog` (`.modal-root` / `.modal-dialog`, drawn as a sheet by
 * `phone/base.css`, with a grab bar that swipes it away), holding one full
 * width button per action and Cancel last, where a thumb ends up.
 *
 * Only the phone layout opens one, so its markup has no desktop styles.
 */

export interface SheetAction {
  label: string;
  /** A link out (Open in Etsy) rather than something this app does. */
  href?: string;
  onSelect?: () => void;
  /** Destructive: drawn in the danger colour. */
  danger?: boolean;
}

export function ActionSheet({
  title,
  actions,
  onClose,
}: {
  title: string;
  actions: SheetAction[];
  onClose: () => void;
}) {
  const titleId = useId();
  const sheet = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-root" role="dialog" aria-modal="true" aria-labelledby={titleId}>
      <div className="modal-backdrop" onClick={onClose} aria-hidden="true" />
      <div ref={sheet} className="modal-dialog m-sheet">
        <SheetGrabber sheetRef={sheet} onDismiss={onClose} />
        <h2 id={titleId} className="m-sheet__title">
          {title}
        </h2>
        <div className="m-sheet__actions">
          {actions.map((action) =>
            action.href !== undefined ? (
              <a
                key={action.label}
                className="m-sheet__action"
                href={action.href}
                target="_blank"
                rel="noreferrer"
                onClick={onClose}
              >
                {action.label}
              </a>
            ) : (
              <button
                key={action.label}
                type="button"
                className={
                  action.danger ? "m-sheet__action m-sheet__action--danger" : "m-sheet__action"
                }
                onClick={() => {
                  onClose();
                  action.onSelect?.();
                }}
              >
                {action.label}
              </button>
            ),
          )}
        </div>
        <button type="button" className="m-sheet__action m-sheet__cancel" onClick={onClose}>
          Cancel
        </button>
      </div>
    </div>
  );
}
