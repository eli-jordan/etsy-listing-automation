import { type ReactNode, useEffect, useId, useRef } from "react";
import { SheetGrabber } from "../phone/SheetGrabber";

/** An in-app confirm: `window.confirm` is browser chrome that cannot be
 * styled like the shell. */

interface Props {
  title: string;
  confirmLabel: string;
  details?: string;
  children?: ReactNode;
  confirmDisabled?: boolean;
  className?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  title,
  confirmLabel,
  details,
  children,
  confirmDisabled = false,
  className,
  onConfirm,
  onCancel,
}: Props) {
  const titleId = useId();
  const sheet = useRef<HTMLDivElement>(null);
  const head = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCancel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="modal-root" role="dialog" aria-modal="true" aria-labelledby={titleId}>
      <div className="modal-backdrop" onClick={onCancel} aria-hidden="true" />
      <div
        ref={sheet}
        className={["modal-dialog confirm-dialog", className].filter(Boolean).join(" ")}
      >
        <SheetGrabber sheetRef={sheet} onDismiss={onCancel} head={head} />
        <h2 ref={head} id={titleId} className="confirm-dialog__title">
          {title}
        </h2>
        {children}
        {details !== undefined && (
          <details className="confirm-dialog__details">
            <summary>Details</summary>
            <p>{details}</p>
          </details>
        )}
        <div className="confirm-dialog__actions">
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onConfirm}
            disabled={confirmDisabled}
            autoFocus
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
